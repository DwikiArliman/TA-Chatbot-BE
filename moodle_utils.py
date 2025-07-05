from datetime import datetime, timedelta
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
import mysql.connector
import os
import time
from urllib.parse import quote

# Koneksi ke DB Moodle
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "moodle_db")
    )

#db_config_moodle = {
#    'host': os.getenv("DB_HOST"),
#    'user': os.getenv("DB_USER"),
#    'password': os.getenv("DB_PASSWORD"),
#    'database': os.getenv("DB_DATABASE"),
#    'port': os.getenv("DB_PORT")
# }

# Konfigurasi untuk Database Sesi (dari TiDB Cloud / PlanetScale)
db_config_session = {
    'host': os.getenv("MYSQLHOST"),
    'user': os.getenv("MYSQLUSER"),
    'password': os.getenv("MYSQLPASSWORD"),
    'database': os.getenv("MYSQLDATABASE"),
    'port': int(os.getenv("MYSQLPORT", 3306)) # Pastikan port adalah integer
}

# Konfigurasi untuk Database Moodle Utama (dari server Moodle Anda)
db_config_moodle = {
    'host': os.getenv("MOODLE_DB_HOST"),
    'user': os.getenv("MOODLE_DB_USER"),
    'password': os.getenv("MOODLE_DB_PASSWORD"),
    'database': os.getenv("MOODLE_DB_DATABASE"),
    'port': int(os.getenv("MOODLE_DB_PORT", 3306))
}

MOODLE_API_URL = "http://20.2.66.68/moodle/webservice/rest/server.php"
MOODLE_URL = "http://20.2.66.68"

def get_jadwal(userid):
    """
    Mengambil jadwal (event) untuk user tertentu yang akan terjadi
    dalam 7 hari ke depan dari sekarang.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 1. Tentukan rentang waktu: dari sekarang hingga 7 hari ke depan
        now_timestamp = int(time.time())
        one_week_later = datetime.now() + timedelta(days=7)
        one_week_later_timestamp = int(one_week_later.timestamp())

        # 2. Modifikasi query untuk memfilter berdasarkan rentang waktu
        # timestart di Moodle disimpan dalam format Unix timestamp (integer).
        query = """
                SELECT name, timestart 
                FROM mdl_event
                WHERE 
                    (eventtype = 'site'
                    OR eventtype = 'course' AND courseid IN (
                        SELECT e.courseid
                        FROM mdl_user_enrolments ue
                        JOIN mdl_enrol e ON ue.enrolid = e.id
                        WHERE ue.userid = %s
                    )
                    OR eventtype = 'user' AND userid = %s)
                    AND timestart BETWEEN %s AND %s
                ORDER BY timestart ASC
        """

        # 3. Eksekusi query dengan parameter tambahan untuk waktu
        cursor.execute(query, (userid,userid, now_timestamp, one_week_later_timestamp))
        
        rows = cursor.fetchall()
        return rows
        # Execute the query with additional parameters for time
        cursor.execute(query, (userid, userid, now_timestamp, one_week_later_timestamp))
        
    except mysql.connector.Error as err:
        print("Database error:", err)
        return []
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
            conn.close()

def get_tugas_quiz_hari_ini(userid):
    """
    Mengambil daftar tugas dan kuis yang memiliki deadline pada hari ini
    untuk seorang pengguna.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 1. Dapatkan rentang waktu untuk hari ini
        start_ts, end_ts = get_today_timestamp_range()

        # 2. Query untuk menggabungkan tugas dan kuis
        query = """
            (
                SELECT
                    'tugas' AS item_type,
                    a.name,
                    a.duedate,
                    c.fullname AS course_name
                FROM mdl_assign a
                JOIN mdl_course c ON a.course = c.id
                JOIN mdl_enrol e ON e.courseid = c.id
                JOIN mdl_user_enrolments ue ON ue.enrolid = e.id
                WHERE a.duedate BETWEEN %s AND %s
                AND ue.userid = %s
            )
            UNION ALL
            (
                SELECT
                    'kuis' AS item_type,
                    q.name,
                    q.timeclose AS duedate,
                    c.fullname AS course_name
                FROM mdl_quiz q
                JOIN mdl_course c ON q.course = c.id
                JOIN mdl_enrol e ON e.courseid = c.id
                JOIN mdl_user_enrolments ue ON ue.enrolid = e.id
                WHERE q.timeclose BETWEEN %s AND %s
                AND ue.userid = %s
            )
            ORDER BY duedate ASC
        """

        cursor.execute(query, (start_ts, end_ts, userid, start_ts, end_ts, userid))
        items = cursor.fetchall()
        return items

    except mysql.connector.Error as err:
        print(f"Database error dalam get_tugas_quiz_hari_ini: {err}")
        return []
    except Exception as e:
        print(f"Error dalam get_tugas_quiz_hari_ini: {e}")
        return []
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def get_db_connection():
    """Membuka koneksi baru ke database Moodle."""
    return mysql.connector.connect(**db_config_moodle)

def simpan_session(session_id, userid, token):
    """Menyimpan atau memperbarui sesi chatbot di database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        sql = """
        INSERT INTO mdl_chatbot_sessions (session_id, userid, token, created_at, updated_at)
        VALUES (%s, %s, %s, NOW(), NOW())
        ON DUPLICATE KEY UPDATE
            userid = %s,
            token = %s,
            updated_at = NOW()
        """
        print(f"Saving chatbot session to DB: session_id={session_id}, userid={userid}, token={token[:5]}...") # Sensor token untuk log
        cursor.execute(sql, (session_id, userid, token, userid, token))
        conn.commit()
    except Exception as e:
        print("Database Error (simpan_session):", e)
    finally:
        cursor.close()
        conn.close()

def get_token_by_userid(userid):
    """Mengambil token dari database berdasarkan userid."""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True, buffered=True)
        query = "SELECT token FROM mdl_chatbot_sessions WHERE userid = %s"
        cursor.execute(query, (userid,))
        result = cursor.fetchone()
        return result["token"] if result else None
    except mysql.connector.Error as err:
        print(f"Database error (get_token_by_userid): {err}")
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def get_today_timestamp_range():
    """Mengembalikan rentang timestamp awal dan akhir hari ini."""
    now = datetime.now()
    start = datetime(now.year, now.month, now.day)
    end = start + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())

def format_tanggal_indonesia(timestamp):
    """Memformat timestamp ke format tanggal dan waktu Indonesia."""
    hari_mapping = {
        'Monday': 'Senin', 'Tuesday': 'Selasa', 'Wednesday': 'Rabu',
        'Thursday': 'Kamis', 'Friday': 'Jumat', 'Saturday': 'Sabtu', 'Sunday': 'Minggu'
    }
    bulan_mapping = {
        'January': 'Januari', 'February': 'Februari', 'March': 'Maret',
        'April': 'April', 'May': 'Mei', 'June': 'Juni',
        'July': 'Juli', 'August': 'Agustus', 'September': 'September',
        'October': 'Oktober', 'November': 'November', 'December': 'Desember'
    }
    dt = datetime.fromtimestamp(timestamp)
    hari = hari_mapping.get(dt.strftime('%A'), dt.strftime('%A'))
    bulan = bulan_mapping.get(dt.strftime('%B'), dt.strftime('%B'))
    return f"{hari}, {dt.day:02d} {bulan} {dt.year} Pukul: {dt.strftime('%H:%M')}"

#def get_user_id_from_session(session_id):
    """Mengekstrak user ID dari format session ID Dialogflow yang diharapkan."""
    if session_id and session_id.startswith("moodle-user-"):
        try:
            user_part = session_id.replace("moodle-user-", "").split('-')[0]
            if user_part.isdigit():
                return int(user_part)
        except Exception as e:
            print("Gagal parsing user ID dari session:", e)
    return None
def get_user_session_data(session_id):
    """
    Mengambil data user (userid dan token) dari database berdasarkan session_id.
    Mengembalikan dictionary jika ditemukan, atau None jika tidak.
    """
    if not session_id:
        return None

    conn = None # Inisialisasi conn di luar try
    try:
        conn = get_db_connection()
        # Menggunakan dictionary=True agar hasil bisa diakses seperti: data['userid']
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT userid, token FROM mdl_chatbot_sessions WHERE session_id = %s",
            (session_id,)
        )
        user_data = cursor.fetchone()
        return user_data
    except Exception as e:
        print(f"Error getting user session data: {e}")
        return None
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

def get_user_fullname(userid):
    """
    Mengambil nama lengkap user dari tabel mdl_user berdasarkan userid.
    """
    if not userid:
        return "Pengguna" # Nama default jika userid tidak ada

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT firstname, lastname FROM mdl_user WHERE id = %s",
            (userid,)
        )
        user = cursor.fetchone()
        if user:
            # Menggabungkan nama depan dan nama belakang
            return f"{user['firstname']} {user['lastname']}".strip()
        return "Pengguna"
    except Exception as e:
        print(f"Error getting user fullname: {e}")
        return "Pengguna"
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

def get_userid_from_token(token):
    """Mengambil userid dari mdl_chatbot_sessions berdasarkan token atau Moodle API."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT userid FROM mdl_chatbot_sessions WHERE token = %s LIMIT 1", (token,))
        row = cursor.fetchone()
        if row:
            return row['userid']
        else:
            try:
                params = {
                    "wstoken": token,
                    "wsfunction": "core_webservice_get_site_info",
                    "moodlewsrestformat": "json"
                }
                response = requests.get(MOODLE_API_URL, params=params, timeout=5)
                response.raise_for_status()
                result = response.json()
                moodle_userid = result.get("userid")
                if moodle_userid:
                    print(f"User ID {moodle_userid} fetched from Moodle API for token.")
                    return moodle_userid
                else:
                    print("Moodle API did not return userid for the provided token.")
                    return None
            except Exception as e:
                print(f"Error fetching Moodle user info from API (get_userid_from_token fallback): {e}")
                return None
    except Exception as e:
        print("Error get_userid_from_token (DB lookup):", e)
        return None
    finally:
        cursor.close()
        conn.close()

def is_user_admin(userid):
    """Memeriksa apakah user adalah admin Moodle."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        query = """
        SELECT COUNT(ra.id) FROM mdl_role_assignments ra
        JOIN mdl_context ctx ON ctx.id = ra.contextid
        WHERE ra.userid = %s AND ra.roleid = 1 AND ctx.contextlevel = 10;
        """ # roleid 1 for manager (admin) and contextlevel 10 for system context
        cursor.execute(query, (userid,))
        is_admin = cursor.fetchone()[0] > 0
        return is_admin
    except Exception as e:
        print("Error is_user_admin:", e)
        return False
    finally:
        cursor.close()
        conn.close()

def is_user_teacher(userid):
    """
    Memeriksa apakah seorang pengguna memiliki peran sebagai dosen
    (teacher atau editingteacher) di salah satu mata kuliah.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Query untuk menghitung berapa kali user ini berperan sebagai dosen
        query = """
            SELECT COUNT(ra.id) AS teacher_role_count
            FROM mdl_role_assignments ra
            JOIN mdl_role r ON ra.roleid = r.id
            WHERE ra.userid = %s
            AND r.shortname IN ('teacher', 'editingteacher')
        """
        cursor.execute(query, (userid,))
        result = cursor.fetchone()
        
        # Jika jumlahnya lebih dari 0, maka dia adalah dosen
        if result and result['teacher_role_count'] > 0:
            return True
        return False

    except Exception as e:
        print(f"Error dalam is_user_teacher: {e}")
        return False # Anggap bukan dosen jika terjadi error
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def get_course_fullname_by_id(course_id):
    """Mengambil nama lengkap mata kuliah berdasarkan ID."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = "SELECT fullname FROM mdl_course WHERE id = %s"
        cursor.execute(query, (course_id,))
        result = cursor.fetchone()
        return result["fullname"] if result else None
    except mysql.connector.Error as err:
        print("DB error saat ambil nama mata kuliah:", err)
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def get_course_section_content(course_id, section_label):
    """Mengambil konten section dari mata kuliah."""
    query = """
    SELECT
        cs.id AS section_id,
        cs.name AS section_label,
        md.name AS module_type,
        cm.id AS course_module_id,
        cm.instance,
        COALESCE(r.name, a.name, q.name, f.name, u.name, p.name, l.name) AS activity_name,
        a.duedate,
        a.allowsubmissionsfromdate,
        q.timeopen AS quiz_open,
        q.timeclose AS quiz_close
    FROM mdl_course_sections cs
    JOIN mdl_course_modules cm ON cm.section = cs.id
    JOIN mdl_modules md ON md.id = cm.module
    LEFT JOIN mdl_resource r ON r.id = cm.instance AND md.name = 'resource'
    LEFT JOIN mdl_assign a ON a.id = cm.instance AND md.name = 'assign'
    LEFT JOIN mdl_quiz q ON q.id = cm.instance AND md.name = 'quiz'
    LEFT JOIN mdl_forum f ON f.id = cm.instance AND md.name = 'forum'
    LEFT JOIN mdl_url u ON u.id = cm.instance AND md.name = 'url'
    LEFT JOIN mdl_page p ON p.id = cm.instance AND md.name = 'page'
    LEFT JOIN mdl_lesson l ON l.id = cm.instance AND md.name = 'lesson'
    WHERE cs.course = %s
        AND (cs.name = %s OR cs.section = %s) -- Mencari berdasarkan nama atau nomor section
        AND cm.deletioninprogress = 0
    ORDER BY cm.id;
    """

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            section_number = int(section_label)
        except ValueError:
            section_number = -1 # Dummy value if not a number

        cursor.execute(query, (course_id, section_label, section_number))
        results = cursor.fetchall()
        return results
    except Exception as e:
        print(f"Error fetching course section content: {e}")
        return []
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# Ambil tugas & kuis yang masih terbuka
def get_tugas_quiz_minggu_ini(userid):
    """
    Mengambil daftar tugas dan kuis yang memiliki deadline dalam pekan ini
    (Senin hingga Minggu) untuk seorang pengguna.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 1. Tentukan rentang waktu pekan ini (Senin 00:00 - Minggu 23:59)
        today = datetime.now()
        start_of_week = today - timedelta(days=today.weekday())
        start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
        
        end_of_week = start_of_week + timedelta(days=6)
        end_of_week = end_of_week.replace(hour=23, minute=59, second=59, microsecond=0)

        start_timestamp = int(start_of_week.timestamp())
        end_timestamp = int(end_of_week.timestamp())

        # 2. PERBAIKAN: Query menggunakan mdl_context dan mdl_role_assignments
        #    Ini adalah cara yang lebih standar dan akurat untuk memeriksa
        #    apakah seorang user adalah 'student' (roleid = 5) di sebuah mata kuliah.
        query = """
            (
                SELECT
                    'tugas' AS item_type,
                    a.name,
                    a.duedate,
                    c.fullname AS course_name
                FROM mdl_assign a
                JOIN mdl_course c ON a.course = c.id
                JOIN mdl_context ctx ON ctx.instanceid = c.id AND ctx.contextlevel = 50
                JOIN mdl_role_assignments ra ON ra.contextid = ctx.id
                WHERE a.duedate BETWEEN %s AND %s
                AND ra.userid = %s AND ra.roleid = 5
            )
            UNION ALL
            (
                SELECT
                    'kuis' AS item_type,
                    q.name,
                    q.timeclose AS duedate,
                    c.fullname AS course_name
                FROM mdl_quiz q
                JOIN mdl_course c ON q.course = c.id
                JOIN mdl_context ctx ON ctx.instanceid = c.id AND ctx.contextlevel = 50
                JOIN mdl_role_assignments ra ON ra.contextid = ctx.id
                WHERE q.timeclose BETWEEN %s AND %s
                AND ra.userid = %s AND ra.roleid = 5
            )
            ORDER BY duedate ASC
        """

        cursor.execute(query, (start_timestamp, end_timestamp, userid, start_timestamp, end_timestamp, userid))
        items = cursor.fetchall()

        # 3. Format hasil untuk ditampilkan
        if not items:
            return "Tidak ada tugas atau kuis dengan deadline pekan ini."

        reply_lines = ["Berikut adalah daftar tugas dan kuis untuk pekan ini:", ""]
        for item in items:
            emoji = "📝" if item['item_type'] == 'tugas' else "🧪"
            reply_lines.append(f"{emoji} {item['name']}")
            reply_lines.append(f"   (Mata Kuliah: {item['course_name']})")
            reply_lines.append(f"   ⏰ Deadline: {format_tanggal_indonesia(item['duedate'])}")
            reply_lines.append("") # Baris kosong sebagai pemisah

        return "\n".join(reply_lines)

    except mysql.connector.Error as err:
        print(f"Database error dalam get_tugas_quiz_minggu_ini: {err}")
        return "Terjadi masalah saat mengakses database."
    except Exception as e:
        print(f"Error dalam get_tugas_quiz_minggu_ini: {e}")
        return "Terjadi kesalahan sistem yang tidak terduga."
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def get_dosen_info_for_mahasiswa(student_userid, partial_course_name):
    """
    Mencari dan mengembalikan nama dosen dari sebuah mata kuliah spesifik,
    namun HANYA jika mahasiswa yang bertanya terdaftar di mata kuliah tersebut.
    
    Args:
        student_userid (int): ID dari mahasiswa yang bertanya.
        partial_course_name (str): Sebagian nama mata kuliah yang dicari.

    Returns:
        str: String balasan yang sudah diformat untuk chatbot.
    """
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Langkah 1: Cari ID dan nama lengkap mata kuliah berdasarkan nama parsial.
        # Menggunakan LIKE %...% agar pencarian lebih fleksibel.
        sql_find_course = "SELECT id, fullname FROM mdl_course WHERE fullname LIKE %s LIMIT 1"
        cursor.execute(sql_find_course, (f"%{partial_course_name}%",))
        course = cursor.fetchone()

        if not course:
            return f"Maaf, saya tidak dapat menemukan mata kuliah yang cocok dengan '{partial_course_name}'."

        course_id = course['id']
        course_fullname = course['fullname']

        # Langkah 2: Verifikasi apakah mahasiswa terdaftar di mata kuliah ini (PENTING!).
        sql_check_enrollment = """
            SELECT COUNT(ue.id) AS enrollment_count
            FROM mdl_user_enrolments ue
            JOIN mdl_enrol e ON ue.enrolid = e.id
            WHERE ue.userid = %s AND e.courseid = %s
        """
        cursor.execute(sql_check_enrollment, (student_userid, course_id))
        enrollment = cursor.fetchone()

        # Jika hasil count adalah 0, berarti tidak terdaftar.
        if not enrollment or enrollment['enrollment_count'] == 0:
            return f"Maaf, Anda tidak terdaftar di mata kuliah '{course_fullname}', jadi saya tidak bisa memberikan info dosen."

        # Langkah 3: Jika terdaftar, baru cari semua pengguna dengan peran dosen.
        # Peran dosen di Moodle biasanya 'editingteacher' (roleid=3) atau 'teacher' (roleid=4).
        # Context level untuk mata kuliah adalah 50.
        sql_find_teachers = """
            SELECT u.firstname, u.lastname
            FROM mdl_user u
            JOIN mdl_role_assignments ra ON ra.userid = u.id
            JOIN mdl_context ctx ON ctx.id = ra.contextid
            JOIN mdl_role r ON r.id = ra.roleid
            WHERE ctx.instanceid = %s
            AND ctx.contextlevel = 50
            AND r.shortname IN ('teacher', 'editingteacher')
            ORDER BY u.lastname, u.firstname
        """
        cursor.execute(sql_find_teachers, (course_id,))
        teachers = cursor.fetchall()

        if not teachers:
            return f"Tidak ada dosen yang ditugaskan untuk mata kuliah '{course_fullname}'."

        # Langkah 4: Format balasan menjadi kalimat yang rapi.
        teacher_names = [f"{t['firstname']} {t['lastname']}" for t in teachers]
        
        if len(teacher_names) == 1:
            reply = f"Dosen untuk mata kuliah {course_fullname} adalah {teacher_names[0]}."
        else:
            # Menggabungkan nama dengan koma, dan kata 'dan' untuk nama terakhir
            dosen_list_str = " dan ".join([", ".join(teacher_names[:-1]), teacher_names[-1]])
            reply = f"Dosen untuk mata kuliah {course_fullname} adalah: {dosen_list_str}."

        return reply

    except mysql.connector.Error as err:
        print(f"Database error in get_dosen_info_for_mahasiswa: {err}")
        return "Terjadi masalah saat mengakses database."
    except Exception as e:
        print(f"Unexpected error in get_dosen_info_for_mahasiswa: {e}")
        return "Terjadi kesalahan yang tidak terduga."
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def get_dosen_profile(partial_teacher_name):
    """
    Mencari profil lengkap seorang dosen dan memformatnya menjadi
    teks biasa (plain text) yang rapi untuk chatbot menggunakan pola list.append().
    
    Args:
        partial_teacher_name (str): Sebagian nama dosen yang dicari.

    Returns:
        str: String balasan yang sudah diformat plain text untuk chatbot.
    """
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        if not conn:
            return "Tidak dapat terhubung ke database. Silakan coba lagi nanti."

        cursor = conn.cursor(dictionary=True)

        # Langkah 1 & 2 tidak ada perubahan.
        sql_find_teacher = """
            SELECT id, firstname, lastname, email, city, country
            FROM mdl_user WHERE CONCAT(firstname, ' ', lastname) LIKE %s AND deleted = 0 AND suspended = 0
            AND id IN (SELECT DISTINCT ra.userid FROM mdl_role_assignments ra JOIN mdl_role r ON r.id = ra.roleid WHERE r.shortname IN ('teacher', 'editingteacher'))
            LIMIT 1
        """
        cursor.execute(sql_find_teacher, (f"%{partial_teacher_name}%",))
        teacher = cursor.fetchone()

        if not teacher:
            return f"Maaf, dosen dengan nama yang mirip '{partial_teacher_name}' tidak dapat ditemukan."

        teacher_id = teacher['id']
        full_name = f"{teacher['firstname']} {teacher['lastname']}"

        sql_find_courses = """
            SELECT c.fullname FROM mdl_course c JOIN mdl_context ctx ON ctx.instanceid = c.id
            JOIN mdl_role_assignments ra ON ra.contextid = ctx.id
            WHERE ctx.contextlevel = 50 AND ra.userid = %s
            AND ra.roleid IN (SELECT id FROM mdl_role WHERE shortname IN ('teacher', 'editingteacher'))
            ORDER BY c.fullname ASC
        """
        cursor.execute(sql_find_courses, (teacher_id,))
        courses = cursor.fetchall()

        # --- PERUBAHAN UTAMA: MENGGUNAKAN POLA LIST.APPEND() ---

        # Langkah 3: Susun semua informasi ke dalam sebuah list.
        reply_lines = []
        
        # Header
        reply_lines.append(f"👤Nama Dosen: {full_name}")

        # Informasi Kontak
        if teacher.get('email'):
            reply_lines.append(f"📧Email: {teacher['email']}")
        if teacher.get('city') and teacher.get('country'):
            country_name = "Indonesia" if teacher.get('country') == "ID" else teacher.get('country')
            reply_lines.append(f"📍Lokasi: {teacher['city']}, {country_name}")


        # Beri jarak jika ada informasi kontak
        if teacher.get('email') or (teacher.get('city') and teacher.get('country')):
            reply_lines.append("")

        # Informasi Mata Kuliah
        if courses:
            reply_lines.append("📚Mata Kuliah yang Diampu:")
            for course in courses:
                reply_lines.append(f"• {course['fullname']}")
        else:
            reply_lines.append(f"📚 Saat ini, {full_name} tidak ditugaskan untuk mengampu mata kuliah apa pun.")

        # Gabungkan semua baris dalam list menjadi satu string dengan pemisah baris baru.
        return "\n".join(reply_lines)

    except mysql.connector.Error as err:
        print(f"Database error in get_dosen_profile: {err}")
        return "Terjadi masalah saat mengakses data. Mohon hubungi administrator."
    except Exception as e:
        print(f"Unexpected error in get_dosen_profile: {e}")
        return "Terjadi kesalahan sistem yang tidak terduga."
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def get_timeline_kegiatan(userid):
    """
    Mengambil daftar semua tugas dan kuis yang akan datang (timeline)
    untuk seorang pengguna, diurutkan berdasarkan tanggal.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 1. Tentukan waktu mulai: dari sekarang
        now_timestamp = int(datetime.now().timestamp())

        # 2. PERBAIKAN: Query ini sekarang memeriksa status pendaftaran (enrolment)
        #    pengguna di sebuah mata kuliah, tidak peduli apa perannya.
        query = """
            (
                SELECT
                    'tugas' AS item_type,
                    a.name,
                    a.duedate,
                    c.fullname AS course_name
                FROM mdl_assign a
                JOIN mdl_course c ON a.course = c.id
                JOIN mdl_enrol e ON e.courseid = c.id
                JOIN mdl_user_enrolments ue ON ue.enrolid = e.id
                WHERE a.duedate >= %s
                AND ue.userid = %s
            )
            UNION ALL
            (
                SELECT
                    'kuis' AS item_type,
                    q.name,
                    q.timeclose AS duedate,
                    c.fullname AS course_name
                FROM mdl_quiz q
                JOIN mdl_course c ON q.course = c.id
                JOIN mdl_enrol e ON e.courseid = c.id
                JOIN mdl_user_enrolments ue ON ue.enrolid = e.id
                WHERE q.timeclose >= %s
                AND ue.userid = %s
            )
            ORDER BY duedate ASC
        """

        cursor.execute(query, (now_timestamp, userid, now_timestamp, userid))
        items = cursor.fetchall()

        # 3. Format hasil untuk ditampilkan
        if not items:
            return "Tidak ada kegiatan (tugas/kuis) yang akan datang."

        reply_lines = ["🗓️ Timeline Kegiatan Anda:", ""]
        for item in items:
            emoji = "📝" if item['item_type'] == 'tugas' else "🧪"
            reply_lines.append(f"{emoji} {item['name']}")
            reply_lines.append(f"   (Mata Kuliah: {item['course_name']})")
            reply_lines.append(f"   ⏰ Deadline: {format_tanggal_indonesia(item['duedate'])}")
            reply_lines.append("") # Baris kosong sebagai pemisah

        return "\n".join(reply_lines)

    except mysql.connector.Error as err:
        print(f"Database error dalam get_timeline_kegiatan: {err}")
        return "Terjadi masalah saat mengakses database."
    except Exception as e:
        print(f"Error dalam get_timeline_kegiatan: {e}")
        return "Terjadi kesalahan sistem yang tidak terduga."
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def get_materi_matkul(userid, partial_materi_name):
    """
    Mencari file materi (PDF/PPT) berdasarkan nama parsial di semua
    mata kuliah yang diikuti oleh pengguna dan mengembalikan link unduhnya.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Query ini cukup kompleks karena harus menghubungkan beberapa tabel:
        # mdl_files -> mdl_context -> mdl_course_modules -> mdl_resource -> mdl_course -> mdl_user_enrolments
        query = """
            SELECT
                f.contextid, f.component, f.filearea, f.itemid, f.filename,
                r.name AS resource_name,
                c.fullname AS course_name
            FROM mdl_files f
            JOIN mdl_context ctx ON f.contextid = ctx.id
            JOIN mdl_course_modules cm ON ctx.instanceid = cm.id AND ctx.contextlevel = 70
            JOIN mdl_resource r ON cm.instance = r.id
            JOIN mdl_course c ON cm.course = c.id
            JOIN mdl_enrol e ON e.courseid = c.id
            JOIN mdl_user_enrolments ue ON ue.enrolid = e.id
            WHERE
                ue.userid = %s
            AND r.name LIKE %s
            AND f.component = 'mod_resource'
            AND f.filearea = 'content'
            AND f.filename != '.'
            AND (f.mimetype = 'application/pdf' OR f.mimetype LIKE 'application/vnd.ms-powerpoint%' OR f.mimetype LIKE 'application/vnd.openxmlformats-officedocument.presentationml%')
            LIMIT 1
        """

        cursor.execute(query, (userid, f"%{partial_materi_name}%"))
        file_info = cursor.fetchone()

        if not file_info:
            return f"Maaf, saya tidak bisa menemukan materi dengan nama yang mirip '{partial_materi_name}' di mata kuliah Anda."

        # Membuat URL unduh yang valid untuk Moodle
        # Pastikan filename di-encode agar aman untuk URL
        encoded_filename = quote(file_info['filename'])
        download_url = (
            f"{MOODLE_URL}/pluginfile.php/{file_info['contextid']}"
            f"/{file_info['component']}/{file_info['filearea']}"
            f"/{file_info['itemid']}/{encoded_filename}"
        )
        hyperlink = f'<a href="{download_url}" target="_blank" rel="noopener noreferrer">Unduh Materi di Sini</a>'
        reply = (
            f"Saya menemukan materi yang Anda cari:\n\n"
            f"📄Nama File: {file_info['resource_name']}\n"
            f"   (Mata Kuliah: {file_info['course_name']})\n\n"
            f"Silakan unduh melalui tautan berikut:\n"
            f"{hyperlink}" # Ini sekarang berisi tag <a>
        )
        return reply

    # --- PERBAIKAN: Menambahkan blok except dan finally ---
    except mysql.connector.Error as err:
        print(f"Database error dalam get_materi_matkul: {err}")
        return "Terjadi masalah saat mengakses database."
    except Exception as e:
        print(f"Error dalam get_materi_matkul: {e}")
        return "Terjadi kesalahan sistem yang tidak terduga."
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def get_materi_by_section(userid, course_name, section_name):
    """
    Mencari semua file materi (PDF/PPT) dalam section spesifik dari
    sebuah mata kuliah yang diikuti oleh pengguna.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Query ini mencari semua file dalam satu section dari satu mata kuliah
        query = """
            SELECT
                f.contextid, f.component, f.filearea, f.itemid, f.filename,
                r.name AS resource_name,
                c.fullname AS course_name,
                cs.name AS section_name
            FROM mdl_files f
            JOIN mdl_context ctx ON f.contextid = ctx.id
            JOIN mdl_course_modules cm ON ctx.instanceid = cm.id AND ctx.contextlevel = 70
            JOIN mdl_resource r ON cm.instance = r.id
            JOIN mdl_course c ON cm.course = c.id
            JOIN mdl_course_sections cs ON cm.section = cs.id
            JOIN mdl_enrol e ON e.courseid = c.id
            JOIN mdl_user_enrolments ue ON ue.enrolid = e.id
            WHERE
                ue.userid = %s
            AND c.fullname LIKE %s
            AND cs.name LIKE %s
            AND f.component = 'mod_resource'
            AND f.filearea = 'content'
            AND f.filename != '.'
            AND (f.mimetype = 'application/pdf' OR f.mimetype LIKE 'application/vnd.ms-powerpoint%' OR f.mimetype LIKE 'application/vnd.openxmlformats-officedocument.presentationml%')
        """

        cursor.execute(query, (userid, f"%{course_name}%", f"%{section_name}%"))
        files = cursor.fetchall()

        if not files:
            return f"Maaf, saya tidak bisa menemukan materi di '{section_name}' pada mata kuliah '{course_name}'."

        reply_lines = [f"Berikut adalah materi untuk {files[0]['course_name']} di section {files[0]['section_name']}:", ""]

        for file_info in files:
            encoded_filename = quote(file_info['filename'])
            download_url = (
                f"{MOODLE_URL}/pluginfile.php/{file_info['contextid']}"
                f"/{file_info['component']}/{file_info['filearea']}"
                f"/{file_info['itemid']}/{encoded_filename}"
            )
            hyperlink = f'<a href="{download_url}" target="_blank" rel="noopener noreferrer">Unduh di sini</a>'
            
            reply_lines.append(f"📄{file_info['resource_name']} - {hyperlink}")

        return "\n".join(reply_lines)

    except mysql.connector.Error as err:
        print(f"Database error dalam get_materi_by_section: {err}")
        return "Terjadi masalah saat mengakses database."
    except Exception as e:
        print(f"Error dalam get_materi_by_section: {e}")
        return "Terjadi kesalahan sistem yang tidak terduga."
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
