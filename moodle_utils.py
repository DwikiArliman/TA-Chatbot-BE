from datetime import datetime, timedelta
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
import mysql.connector
import os
import time
import re
from urllib.parse import quote

# Koneksi ke DB Moodle
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "moodle_db")
    )

session_port = os.getenv("MYSQLPORT")
moodle_port = os.getenv("MOODLE_DB_PORT")

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
    'port': int(session_port) if session_port else 4000,
    'ssl_ca': 'isrgrootx1.pem',
    'ssl_verify_cert': True
}

# Konfigurasi untuk Database Moodle Utama
db_config_moodle = {
    'host': os.getenv("MOODLE_DB_HOST"),
    'user': os.getenv("MOODLE_DB_USER"),
    'password': os.getenv("MOODLE_DB_PASSWORD"),
    'database': os.getenv("MOODLE_DB_DATABASE"),
    'port': int(moodle_port) if moodle_port else 3306
}

# --- Fungsi Koneksi yang Terpisah ---

def get_session_db_connection():
    """Membuka koneksi ke database SESI (TiDB Cloud)."""
    return mysql.connector.connect(**db_config_session)

def get_moodle_db_connection():
    """Membuka koneksi ke database MOODLE utama."""
    return mysql.connector.connect(**db_config_moodle)


MOODLE_API_URL = "http://20.2.66.68/moodle/webservice/rest/server.php"
MOODLE_URL = "http://20.2.66.68"
#MOODLE_URL = f"http://{os.getenv('MOODLE_DB_HOST', 'localhost')}"

def format_tanggal_indonesia(timestamp):
    if not timestamp: return "Tidak ada tanggal"
    dt = datetime.fromtimestamp(timestamp)
    hari_mapping = {'Monday':'Senin','Tuesday':'Selasa','Wednesday':'Rabu','Thursday':'Kamis','Friday':'Jumat','Saturday':'Sabtu','Sunday':'Minggu'}
    bulan_mapping = {'January':'Januari','February':'Februari','March':'Maret','April':'April','May':'Mei','June':'Juni','July':'Juli','August':'Agustus','September':'September','October':'Oktober','November':'November','December':'Desember'}
    hari = hari_mapping.get(dt.strftime('%A'), dt.strftime('%A'))
    bulan = bulan_mapping.get(dt.strftime('%B'), dt.strftime('%B'))
    return f"{hari}, {dt.day:02d} {bulan} {dt.year} Pukul: {dt.strftime('%H:%M')}"

def get_today_timestamp_range():
    now = datetime.now()
    start = datetime(now.year, now.month, now.day)
    end = start + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())

def simpan_session(session_id, userid, token):
    conn = get_session_db_connection()
    cursor = conn.cursor()
    try:
        sql = "INSERT INTO mdl_chatbot_sessions (session_id, userid, token) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE token = VALUES(token), updated_at = NOW()"
        cursor.execute(sql, (session_id, userid, token))
        conn.commit()
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

def get_user_session_data(session_id):
    conn = get_session_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT userid, token FROM mdl_chatbot_sessions WHERE session_id = %s", (session_id,))
        return cursor.fetchone()
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

def get_user_fullname(userid):
    conn = get_moodle_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT firstname, lastname FROM mdl_user WHERE id = %s", (userid,))
        user = cursor.fetchone()
        return f"{user['firstname']} {user['lastname']}".strip() if user else "Pengguna"
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

def get_jadwal(userid):
    conn = get_moodle_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        now_timestamp = int(time.time())
        one_week_later_timestamp = int((datetime.now() + timedelta(days=7)).timestamp())
        query = """
                SELECT name, timestart FROM mdl_event
                WHERE (eventtype = 'site'
                    OR eventtype = 'course' AND courseid IN (
                        SELECT e.courseid FROM mdl_user_enrolments ue JOIN mdl_enrol e ON ue.enrolid = e.id
                        WHERE ue.userid = %s
                    )
                    OR eventtype = 'user' AND userid = %s)
                    AND timestart BETWEEN %s AND %s
                ORDER BY timestart ASC
                LIMIT 10
        """
        cursor.execute(query, (userid, userid, now_timestamp, one_week_later_timestamp))
        return cursor.fetchall()
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

def get_tugas_quiz_hari_ini(userid):
    conn = get_moodle_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        start_ts, end_ts = get_today_timestamp_range()
        query = """
            (SELECT 'tugas' AS item_type, a.name, a.duedate, c.fullname AS course_name FROM mdl_assign a JOIN mdl_course c ON a.course = c.id JOIN mdl_enrol e ON e.courseid = c.id JOIN mdl_user_enrolments ue ON ue.enrolid = e.id WHERE a.duedate BETWEEN %s AND %s AND ue.userid = %s)
            UNION ALL
            (SELECT 'kuis' AS item_type, q.name, q.timeclose AS duedate, c.fullname AS course_name FROM mdl_quiz q JOIN mdl_course c ON q.course = c.id JOIN mdl_enrol e ON e.courseid = c.id JOIN mdl_user_enrolments ue ON ue.enrolid = e.id WHERE q.timeclose BETWEEN %s AND %s AND ue.userid = %s)
            ORDER BY duedate ASC
            LIMIT 10
        """
        cursor.execute(query, (start_ts, end_ts, userid, start_ts, end_ts, userid))
        return cursor.fetchall()
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

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
    conn = get_moodle_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        query = "SELECT COUNT(ra.id) AS teacher_role_count FROM mdl_role_assignments ra JOIN mdl_role r ON ra.roleid = r.id WHERE ra.userid = %s AND r.shortname IN ('teacher', 'editingteacher')"
        cursor.execute(query, (userid,))
        result = cursor.fetchone()
        return result and result['teacher_role_count'] > 0
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

def get_course_fullname_by_id(course_id):
    """Mengambil nama lengkap mata kuliah berdasarkan ID."""
    try:
        conn = get_moodle_db_connection()
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
        conn = get_moodle_db_connection()
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
    conn = get_moodle_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        today = datetime.now()
        start_of_week = (today - timedelta(days=today.weekday())).replace(hour=0, minute=0, second=0)
        end_of_week = (start_of_week + timedelta(days=6)).replace(hour=23, minute=59, second=59)
        start_timestamp = int(start_of_week.timestamp())
        end_timestamp = int(end_of_week.timestamp())

        query = """
            (SELECT 'tugas' AS item_type, a.name, a.duedate, c.fullname AS course_name FROM mdl_assign a JOIN mdl_course c ON a.course = c.id JOIN mdl_enrol e ON e.courseid = c.id JOIN mdl_user_enrolments ue ON ue.enrolid = e.id WHERE a.duedate BETWEEN %s AND %s AND ue.userid = %s)
            UNION ALL
            (SELECT 'kuis' AS item_type, q.name, q.timeclose AS duedate, c.fullname AS course_name FROM mdl_quiz q JOIN mdl_course c ON q.course = c.id JOIN mdl_enrol e ON e.courseid = c.id JOIN mdl_user_enrolments ue ON ue.enrolid = e.id WHERE q.timeclose BETWEEN %s AND %s AND ue.userid = %s)
            ORDER BY duedate ASC
            LIMIT 15
        """
        cursor.execute(query, (start_timestamp, end_timestamp, userid, start_timestamp, end_timestamp, userid))
        items = cursor.fetchall()

        if not items: return "Tidak ada tugas atau kuis dengan deadline pekan ini."
        reply_lines = ["Berikut adalah daftar tugas dan kuis untuk pekan ini:", ""]
        for item in items:
            emoji = "📝" if item['item_type'] == 'tugas' else "🧪"
            reply_lines.append(f"{emoji} {item['name']} (di {item['course_name']})")
            reply_lines.append(f"   ⏰ Deadline: {format_tanggal_indonesia(item['duedate'])}")
            reply_lines.append("")
        return "\n".join(reply_lines)
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()


def get_dosen_info_for_mahasiswa(student_userid, partial_course_name):
    conn = get_moodle_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, fullname FROM mdl_course WHERE fullname LIKE %s LIMIT 1", (f"%{partial_course_name}%",))
        course = cursor.fetchone()
        if not course: return f"Maaf, saya tidak dapat menemukan mata kuliah '{partial_course_name}'."
        
        cursor.execute("SELECT COUNT(ue.id) AS count FROM mdl_user_enrolments ue JOIN mdl_enrol e ON ue.enrolid = e.id WHERE ue.userid = %s AND e.courseid = %s", (student_userid, course['id']))
        if not cursor.fetchone()['count'] > 0: return f"Maaf, Anda tidak terdaftar di mata kuliah '{course['fullname']}'."

        sql_find_teachers = """
            SELECT u.firstname, u.lastname FROM mdl_user u
            JOIN mdl_role_assignments ra ON ra.userid = u.id
            JOIN mdl_context ctx ON ctx.id = ra.contextid
            WHERE ctx.instanceid = %s AND ctx.contextlevel = 50
            AND ra.roleid IN (SELECT id FROM mdl_role WHERE shortname IN ('teacher', 'editingteacher'))
            ORDER BY u.lastname, u.firstname LIMIT 5
        """
        cursor.execute(sql_find_teachers, (course['id'],))
        teachers = cursor.fetchall()

        if not teachers: return f"Tidak ada dosen yang ditugaskan untuk mata kuliah '{course['fullname']}'."
        
        teacher_names = [f"{t['firstname']} {t['lastname']}" for t in teachers]
        dosen_list_str = " dan ".join([", ".join(teacher_names[:-1]), teacher_names[-1]]) if len(teacher_names) > 1 else teacher_names[0]
        return f"Dosen untuk mata kuliah {course['fullname']} adalah: {dosen_list_str}."
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

def get_dosen_profile(partial_teacher_name):
    conn = get_moodle_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        sql_find_teacher = "SELECT id, firstname, lastname, email, city, country FROM mdl_user WHERE CONCAT(firstname, ' ', lastname) LIKE %s AND deleted = 0 AND suspended = 0 AND id IN (SELECT DISTINCT ra.userid FROM mdl_role_assignments ra JOIN mdl_role r ON r.id = ra.roleid WHERE r.shortname IN ('teacher', 'editingteacher')) LIMIT 1"
        cursor.execute(sql_find_teacher, (f"%{partial_teacher_name}%",))
        teacher = cursor.fetchone()
        if not teacher: return f"Maaf, dosen dengan nama '{partial_teacher_name}' tidak ditemukan."
        
        sql_find_courses = "SELECT c.fullname FROM mdl_course c JOIN mdl_context ctx ON ctx.instanceid = c.id JOIN mdl_role_assignments ra ON ra.contextid = ctx.id WHERE ctx.contextlevel = 50 AND ra.userid = %s AND ra.roleid IN (SELECT id FROM mdl_role WHERE shortname IN ('teacher', 'editingteacher')) ORDER BY c.fullname ASC LIMIT 20"
        cursor.execute(sql_find_courses, (teacher['id'],))
        courses = cursor.fetchall()
        
        full_name = f"{teacher['firstname']} {teacher['lastname']}"
        reply_lines = [f"👤 Nama Dosen: {full_name}"]
        if teacher.get('email'): reply_lines.append(f"📧 Email: {teacher['email']}")
        if teacher.get('city'): reply_lines.append(f"📍 Lokasi: {teacher.get('city')}")
        reply_lines.append("")
        
        if courses:
            reply_lines.append("📚 Mata Kuliah yang Diampu:")
            for course in courses: reply_lines.append(f"• {course['fullname']}")
        else:
            reply_lines.append(f"📚 Saat ini, {full_name} tidak mengampu mata kuliah apa pun.")
            
        return "\n".join(reply_lines)
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

def get_timeline_kegiatan(userid, limit=7, offset=0):
    conn = get_moodle_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        now_timestamp = int(datetime.now().timestamp())
        future_limit_timestamp = int((datetime.now() + timedelta(days=90)).timestamp())
        query = """
            (SELECT 'tugas' AS item_type, a.name, a.duedate, c.fullname AS course_name FROM mdl_assign a JOIN mdl_course c ON a.course = c.id JOIN mdl_enrol e ON e.courseid = c.id JOIN mdl_user_enrolments ue ON ue.enrolid = e.id WHERE a.duedate BETWEEN %s AND %s AND ue.userid = %s)
            UNION ALL
            (SELECT 'kuis' AS item_type, q.name, q.timeclose AS duedate, c.fullname AS course_name FROM mdl_quiz q JOIN mdl_course c ON q.course = c.id JOIN mdl_enrol e ON e.courseid = c.id JOIN mdl_user_enrolments ue ON ue.enrolid = e.id WHERE q.timeclose BETWEEN %s AND %s AND ue.userid = %s)
            ORDER BY duedate ASC LIMIT %s OFFSET %s
        """
        cursor.execute(query, (now_timestamp, future_limit_timestamp, userid, now_timestamp, future_limit_timestamp, userid, limit, offset))
        items = cursor.fetchall()
        if not items: return "Tidak ada kegiatan (tugas/kuis) yang akan datang dalam 90 hari ke depan."
        reply_lines = [f"🗓️ Timeline Kegiatan Anda ({limit} berikutnya):", ""]
        for item in items:
            emoji = "📝" if item['item_type'] == 'tugas' else "🧪"
            reply_lines.append(f"{emoji} {item['name']} (di {item['course_name']})")
            reply_lines.append(f"   ⏰ Deadline: {format_tanggal_indonesia(item['duedate'])}")
            reply_lines.append("")
        return "\n".join(reply_lines)
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()


def get_materi_matkul(userid, partial_materi_name):
    conn = get_moodle_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        query = "SELECT f.contextid, f.component, f.filearea, f.itemid, f.filename, r.name AS resource_name, c.fullname AS course_name FROM mdl_files f JOIN mdl_context ctx ON f.contextid = ctx.id JOIN mdl_course_modules cm ON ctx.instanceid = cm.id AND ctx.contextlevel = 70 JOIN mdl_resource r ON cm.instance = r.id JOIN mdl_course c ON cm.course = c.id JOIN mdl_enrol e ON e.courseid = c.id JOIN mdl_user_enrolments ue ON ue.enrolid = e.id WHERE ue.userid = %s AND r.name LIKE %s AND f.component = 'mod_resource' AND f.filearea = 'content' AND f.filename != '.' AND (f.mimetype = 'application/pdf' OR f.mimetype LIKE 'application/vnd.ms-powerpoint%' OR f.mimetype LIKE 'application/vnd.openxmlformats-officedocument.presentationml%') LIMIT 1"
        cursor.execute(query, (userid, f"%{partial_materi_name}%"))
        file_info = cursor.fetchone()
        if not file_info: return f"Maaf, materi '{partial_materi_name}' tidak ditemukan."
        encoded_filename = quote(file_info['filename'])
        download_url = f"{MOODLE_URL}/pluginfile.php/{file_info['contextid']}/{file_info['component']}/{file_info['filearea']}/{file_info['itemid']}/{encoded_filename}"
        hyperlink = f'<a href="{download_url}" target="_blank">Unduh di Sini</a>'
        return f"Saya menemukan materi: {file_info['resource_name']} di mata kuliah {file_info['course_name']}.\n{hyperlink}"
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

def get_materi_by_section(userid, course_name, section_name):
    conn = get_moodle_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        query = "SELECT f.contextid, f.component, f.filearea, f.itemid, f.filename, r.name AS resource_name, c.fullname AS course_name, cs.name AS section_name FROM mdl_files f JOIN mdl_context ctx ON f.contextid = ctx.id JOIN mdl_course_modules cm ON ctx.instanceid = cm.id AND ctx.contextlevel = 70 JOIN mdl_resource r ON cm.instance = r.id JOIN mdl_course c ON cm.course = c.id JOIN mdl_course_sections cs ON cm.section = cs.id JOIN mdl_enrol e ON e.courseid = c.id JOIN mdl_user_enrolments ue ON ue.enrolid = e.id WHERE ue.userid = %s AND c.fullname LIKE %s AND cs.name LIKE %s AND f.component = 'mod_resource' AND f.filearea = 'content' AND f.filename != '.' AND (f.mimetype = 'application/pdf' OR f.mimetype LIKE 'application/vnd.ms-powerpoint%') LIMIT 15"
        cursor.execute(query, (userid, f"%{course_name}%", f"%{section_name}%"))
        files = cursor.fetchall()
        if not files: return f"Maaf, saya tidak bisa menemukan materi di '{section_name}' pada mata kuliah '{course_name}'."
        reply_lines = [f"Materi untuk {files[0]['course_name']} di section {files[0]['section_name']}:", ""]
        for file_info in files:
            encoded_filename = quote(file_info['filename'])
            download_url = f"{MOODLE_URL}/pluginfile.php/{file_info['contextid']}/{file_info['component']}/{file_info['filearea']}/{file_info['itemid']}/{encoded_filename}"
            hyperlink = f'<a href="{download_url}" target="_blank">Unduh</a>'
            reply_lines.append(f"📄 {file_info['resource_name']} - {hyperlink}")
        return "\n".join(reply_lines)
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()
