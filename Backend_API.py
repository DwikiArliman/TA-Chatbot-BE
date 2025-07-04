from datetime import datetime, timedelta
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
import mysql.connector

app = Flask(__name__)
CORS(app, supports_credentials=True, origins=["http://localhost:5000"])

USER_TOKENS = {
    "admin": "b7385120705a85eeb859e54c2ac5adad",
    "remigio": "01641dfdb56dfc7530a85de5179e2848",
    "adoria": "8cb1b92ed3d8490dcdf8ab67520cebb6",
    "kenny": "9117463d48feb4f59a23393868795dc2",
    "jordi": "0d4944592f2cdc3474af96e5a24c7dc5",
    "michael": "55a8c71c11abbc63d7111c5042e5c7b7"
}

MOODLE_API_URL = "http://localhost/Mymoodle/moodle/webservice/rest/server.php"

db_config_moodle = {
    'host': 'localhost',
    'user': 'root',       
    'password': '',       
    'database': 'moodle_db'  
}

def get_db_connection():
    return mysql.connector.connect(**db_config_moodle)

def simpan_session(session_id, userid, token):
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
        print("Saving session to DB Chatbot:", session_id, userid, token)
        cursor.execute(sql, (session_id, userid, token, userid, token))
        conn.commit()
    except Exception as e:
        print("Database Error (simpan_session):", e)
    finally:
        cursor.close()
        conn.close()

def save_dialogflow_session(session_id, userid, df_session_id, token):
    conn = get_db_connection()
    cursor = conn.cursor()
    print("Saving Session to DB Dialogflow:", df_session_id, session_id, userid, token)
    try:
        cursor.execute("""
            INSERT INTO mdl_dialogflow_sessions 
            (df_session_id, session_id, userid, token, created_at, updated_at)
            VALUES (%s, %s, %s, %s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE 
                session_id = %s,
                userid = %s,
                token = %s,
                updated_at = NOW()
        """, 
        (df_session_id, session_id, userid, token, session_id, userid, token))
        conn.commit()
    except Exception as e:
        print("Database Error (save_dialogflow_session):", e)
    finally:
        cursor.close()
        conn.close()


def get_token_by_userid(userid):
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
        print(f"Database error: {err}")
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def get_today_timestamp_range():
    now = datetime.now()
    start = datetime(now.year, now.month, now.day)
    end = start + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())

def format_tanggal_indonesia(timestamp):
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

#Backup Get_userid_from_token
#def get_userid_from_token(token):
    for userid, t in USER_TOKENS.items():
        if t == token:
            return userid
    return None

def get_user_id_from_session(session_id):
    if session_id and session_id.startswith("moodle-user-"):
        try:
            user_part = session_id.replace("moodle-user-", "")
            if user_part.isdigit():
                return int(user_part)
        except Exception as e:
            print("Gagal parsing user ID dari session:", e)
    return None


def get_userid_from_token(token):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT userid FROM mdl_chatbot_sessions WHERE token = %s LIMIT 1", (token,))
        row = cursor.fetchone()
        return row['userid'] if row else None
    except Exception as e:
        print("Error get_userid_from_token:", e)
        return None
    finally:
        cursor.close()
        conn.close()

def is_user_admin(userid):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT username FROM mdl_user WHERE id = %s LIMIT 1", (userid,))
        row = cursor.fetchone()
        if row and row['username'].lower() == "admin":
            return True
        return False
    except Exception as e:
        print("Error is_user_admin:", e)
        return False
    finally:
        cursor.close()
        conn.close()

def get_jadwal_from_db(userid):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT name, timestart FROM mdl_event
            WHERE userid = %s
            ORDER BY timestart ASC
        """
        cursor.execute(query, (userid,))
        rows = cursor.fetchall()
        return rows
    except mysql.connector.Error as err:
        print("Database error:", err)
        return []
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def get_course_fullname_by_id(course_id):
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
    query = """
    SELECT 
        cs.id AS section_id,
        cs.name AS section_label,
        md.name AS module_type,
        cm.id AS course_module_id,
        cm.instance,
        COALESCE(r.name, a.name, q.name, f.name, u.name) AS activity_name,
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
    WHERE cs.course = %s
        AND cs.name = %s
        AND cm.deletioninprogress = 0
    ORDER BY cm.id;
    """

    conn = None
    cursor = None
    try:
        conn = get_db_connection()  # harus ada fungsi ini yang mengembalikan koneksi DB
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, (course_id, section_label))
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

def format_course_section_contents(contents, section_name=""):
    if not contents:
        return "Tidak ada konten ditemukan di section ini."

    lines = [f"📁 {section_name}", "──────────────────────"]

    for item in contents:
        nama = item.get('activity_name', "Tanpa nama")
        tipe = item.get('module_type', "").capitalize()

        emoji = {
            "Assign": "📝",
            "Quiz": "🧪",
            "Forum": "💬",
            "Resource": "📄",
            "Page": "📘",
        }.get(tipe, "📌")

        lines.append(f"{emoji} {nama}")
        
        # Tambahkan informasi tanggal, jika ada
        if item.get("allowsubmissionsfromdate"):
            lines.append(f"──────────────────────📅 Dibuka   : {format_tanggal_indonesia(item['allowsubmissionsfromdate'])}")
            lines.append("\u00A0" * 35)
        if item.get("duedate"):
            lines.append(f"⏰ Deadline : {format_tanggal_indonesia(item['duedate'])}")
        if item.get("quiz_open"):
            lines.append(f"──────────────────────📅 Dibuka   : {format_tanggal_indonesia(item['quiz_open'])}")
            lines.append("\u00A0" * 35)
        if item.get("quiz_close"):
            lines.append(f"⏰ Ditutup  : {format_tanggal_indonesia(item['quiz_close'])}")

        lines.append("──────────────────────")  # Tambah newline antar aktivitas

    return "\n".join(lines)

def get_tugas_hari_ini(userid):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        start_ts, end_ts = get_today_timestamp_range()

        query = """
            SELECT a.name AS assignment_name, a.duedate, c.fullname AS course_name
            FROM mdl_assign a
            JOIN mdl_course c ON a.course = c.id
            JOIN mdl_context ctx ON ctx.instanceid = c.id AND ctx.contextlevel = 50
            JOIN mdl_role_assignments ra ON ra.contextid = ctx.id
            WHERE a.duedate BETWEEN %s AND %s
                AND ra.userid = %s
            ORDER BY a.duedate ASC
        """
        cursor.execute(query, (start_ts, end_ts, userid))
        return cursor.fetchall()
    except Exception as e:
        print(f"Error get_tugas_hari_ini: {e}")
        return []
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def get_dosen_info_for_mahasiswa(student_id, course_name):
    # Cek course_id dari nama course
    course = db_query("SELECT id FROM mdl_course WHERE fullname ILIKE %s", [f"%{course_name}%"])
    if not course:
        return "Mata kuliah tidak ditemukan."

    course_id = course[0]["id"]

    # Cari dosen yang mengajar course ini
    query = """
        SELECT u.firstname, u.lastname, u.email
        FROM mdl_user u
        JOIN mdl_role_assignments ra ON ra.userid = u.id
        JOIN mdl_context ctx ON ctx.id = ra.contextid
        JOIN mdl_course c ON c.id = ctx.instanceid
        JOIN mdl_role r ON r.id = ra.roleid
        WHERE r.shortname = 'editingteacher' AND c.id = %s
    """
    dosen = db_query(query, [course_id])
    if not dosen:
        return "Tidak ditemukan dosen untuk mata kuliah ini."

    d = dosen[0]
    return f"Dosen untuk {course_name} adalah {d['firstname']} {d['lastname']}, email: {d['email']}"

def get_mahasiswa_info_for_dosen(dosen_id, course_name):
    # Cek course_id yang diampu dosen
    query = """
        SELECT c.id FROM mdl_course c
        JOIN mdl_context ctx ON ctx.instanceid = c.id AND ctx.contextlevel = 50
        JOIN mdl_role_assignments ra ON ra.contextid = ctx.id
        WHERE ra.userid = %s AND c.fullname ILIKE %s
    """
    course = db_query(query, [dosen_id, f"%{course_name}%"])
    if not course:
        return "Anda tidak mengajar mata kuliah ini."

    course_id = course[0]["id"]

    # Ambil semua mahasiswa di course ini
    query = """
        SELECT u.firstname, u.lastname, u.email
        FROM mdl_user u
        JOIN mdl_role_assignments ra ON ra.userid = u.id
        JOIN mdl_context ctx ON ctx.id = ra.contextid
        JOIN mdl_course c ON c.id = ctx.instanceid
        JOIN mdl_role r ON r.id = ra.roleid
        WHERE r.shortname = 'student' AND c.id = %s
    """
    mahasiswa = db_query(query, [course_id])
    if not mahasiswa:
        return "Tidak ada mahasiswa yang terdaftar di mata kuliah ini."

    daftar = "\n".join([f"- {m['firstname']} {m['lastname']} ({m['email']})" for m in mahasiswa])
    return f"Daftar mahasiswa di kelas {course_name}:\n{daftar}"


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    session_id = data['session_id']
    userid = data['userid']
    token = data['token']
    df_session_id = data.get('df_session_id')

    # Simpan ke tabel chatbot_sessions
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO mdl_chatbot_sessions (session_id, userid, token, created_at, updated_at)
        VALUES (%s, %s, %s, NOW(), NOW())
        ON DUPLICATE KEY UPDATE 
            token = VALUES(token),
            updated_at = NOW()
        """, (session_id, userid, token))
    conn.commit()

    # Simpan ke tabel mdl_dialogflow_sessions (jika ada df_session_id)
    if df_session_id:
        cursor.execute("""
            INSERT INTO mdl_dialogflow_sessions (df_session_id, session_id, userid, token, created_at, updated_at)
            VALUES (%s, %s, %s, %s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE 
                userid = VALUES(userid), 
                token = VALUES(token),
                updated_at = NOW()
        """, (df_session_id, session_id, userid, token))

        conn.commit()
        conn.close()

    return jsonify({'status': 'success'})

@app.route('/send-token', methods=['POST'])
def send_token():
    data = request.get_json()
    session_id = data.get("session_id")
    token = data.get("token")

    if not session_id or not token:
        return jsonify({"status": "error", "message": "session_id dan token harus diberikan"}), 400

    userid = get_userid_from_token(token)
    if not userid:
        try:
            params = {
                "wstoken": token,
                "wsfunction": "core_webservice_get_site_info",
                "moodlewsrestformat": "json"
            }
            response = requests.get(MOODLE_API_URL, params=params, timeout=5)
            response.raise_for_status()
            result = response.json()
            userid = result.get("username") or "unknown"
        except Exception as e:
            print("Gagal ambil user info:", e)
            return jsonify({"status": "error", "message": "Token tidak valid"}), 400

    simpan_session(session_id, userid, token)
    return jsonify({"status": "success", "message": "Token disimpan dan session berhasil dihubungkan."})

@app.route('/webhook', methods=['POST'])
def webhook():
    req = request.get_json()
    parameters = req.get("queryResult", {}).get("parameters", {})
    # Ambil session ID dari path
    session_path = req.get("session", "")
    session_id = session_path.rsplit("/", 1)[-1]  # e.g. 'moodle-user-2'

    # Ambil user_id dari session
    userid = get_user_id_from_session(session_id)

    if not userid:
        return jsonify({"fulfillmentText": "Silakan login terlebih dahulu agar saya bisa mengenali Anda."})

    user_token = get_token_by_userid(userid)
    if not user_token:
        return jsonify({"fulfillmentText": "Token untuk user ini tidak ditemukan. Silakan login kembali."})

    intent_name = req.get("queryResult", {}).get("intent", {}).get("displayName", "")
    user_utterance = req.get("queryResult", {}).get("queryText", "")

    if intent_name == "Jadwal_Kelas_Mahasiswa":
        course_param = parameters.get("course_id")
        waktu_param = parameters.get("waktu")
        course_id = str(course_param) if course_param and str(course_param).isdigit() else None

        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)

            if waktu_param == "minggu ini":
                start_ts = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
                end_ts = int((datetime.now() + timedelta(days=7)).replace(hour=23, minute=59, second=59).timestamp())
            else:
            # Default: hanya hari ini
                start_ts, end_ts = get_today_timestamp_range()

            if course_id:
                # Pastikan user ikut course ini
                cursor.execute("""
                    SELECT 1 FROM mdl_enrol e
                    JOIN mdl_user_enrolments ue ON ue.enrolid = e.id
                    WHERE e.courseid = %s AND ue.userid = %s
                """, (course_id, userid))
                if cursor.fetchone() is None:
                    return jsonify({"fulfillmentText": f"Anda tidak terdaftar di mata kuliah ID {course_id}."})
                
                cursor.execute("""
                    SELECT name, timestart FROM mdl_event
                    WHERE courseid = %s AND timestart BETWEEN %s AND %s AND visible = 1
                    ORDER BY timestart ASC
                """, (course_id, start_ts, end_ts))
            else:
                # Ambil semua course yang user ikut
                cursor.execute("""
                    SELECT DISTINCT e.courseid
                    FROM mdl_enrol e
                    JOIN mdl_user_enrolments ue ON ue.enrolid = e.id
                    WHERE ue.userid = %s
                """, (userid,))
                courses = cursor.fetchall()
                course_ids = [row['courseid'] for row in courses]

                if not course_ids:
                    return jsonify({"fulfillmentText": "Anda tidak terdaftar di mata kuliah apapun."})

                format_strings = ','.join(['%s'] * len(course_ids))
                query = f"""
                    SELECT name, timestart FROM mdl_event
                    WHERE courseid IN ({format_strings}) AND timestart BETWEEN %s AND %s AND visible = 1
                    ORDER BY timestart ASC
                """
                cursor.execute(query, (*course_ids, start_ts, end_ts))

            rows = cursor.fetchall()

            if course_id:
                course_name = get_course_fullname_by_id(course_id)
                course_desc = f"mata kuliah '{course_name}'" if course_name else f"mata kuliah ID {course_id}"
            else:
                course_desc = "hari ini"

            if not rows:
                return jsonify({"fulfillmentText": f"Tidak ada jadwal ditemukan untuk {course_desc} pada hari ini."})

            teks_event = [
                f"{row['name']} pada {format_tanggal_indonesia(row['timestart'])}"
                for row in rows
            ]
            jawaban = f"Berikut jadwal kamu untuk {course_desc}:\n" + "\n".join(teks_event)
            return jsonify({"fulfillmentText": jawaban})
        

        except Exception as e:
            print("Gagal ambil jadwal:", e)
            return jsonify({"fulfillmentText": "Terjadi kesalahan saat mengambil jadwal. Silakan coba lagi nanti."})

        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    elif intent_name == "Tanya_Pekan":
        token = parameters.get("token")  # token wajib dikirim di request dari frontend/chatbot
        userid = get_userid_from_token(token)
        
        if not userid:
            return jsonify({"fulfillmentText": "Session tidak valid, silakan login ulang."})
        
        # Cek apakah user admin
        user_is_admin = is_user_admin(userid)
        
        # Cek apakah ada input username admin dari user (misal dari intent parameter)
        input_username = parameters.get("username", "").lower()
        
        if input_username == "admin" and not user_is_admin:
            return jsonify({"fulfillmentText": "Kamu bukan admin."})
        
        course_id = parameters.get("course_id")
        section_label = parameters.get("section_label")
        
        if not course_id or not section_label:
            return jsonify({"fulfillmentText": "Mohon berikan ID mata kuliah dan nama section yang ingin dilihat."})

        # Cek enrolment user di course
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT 1 FROM mdl_user_enrolments ue
                JOIN mdl_enrol e ON ue.enrolid = e.id
                WHERE ue.userid = %s AND e.courseid = %s
                LIMIT 1
            """, (userid, course_id))
            enrolled = cursor.fetchone()
            
            if not enrolled:
                return jsonify({"fulfillmentText": "Kamu tidak ada di kursus ini."})
            
            contents = get_course_section_content(course_id, section_label)
            if contents:
                hasil_format = format_course_section_contents(contents)
                return jsonify({"fulfillmentText": f"📂 Berikut isi dari {section_label}  {hasil_format}"})
            else:
                return jsonify({"fulfillmentText": f"Tidak ditemukan konten untuk '{section_label}' atau nama section tidak sesuai."})
        except Exception as e:
            print("Error cek enrolment atau ambil konten:", e)
            return jsonify({"fulfillmentText": "Terjadi kesalahan saat memproses permintaan."})
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    elif intent_name == "Tugas_Quiz_Hari_Ini_Open":
        userid = parameters.get("userid")  # ambil userid dari parameter
        course_name = parameters.get("course_name")  # kalau user menyebut nama kursus
        try:
            now = int(datetime.now().timestamp())
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)

            # Ambil daftar course_id dan fullname yang user ikuti
            cursor.execute("""
                SELECT DISTINCT c.id, c.fullname
                FROM mdl_course c
                JOIN mdl_user_enrolments ue ON ue.userid = %s
                JOIN mdl_enrol e ON e.id = ue.enrolid AND e.courseid = c.id
            """, (userid,))
            enrolled_courses = cursor.fetchall()

            if not enrolled_courses:
                return jsonify({"fulfillmentText": "Kamu belum terdaftar di kursus apapun."})

            # Jika user menyebut course_name, cek apakah dia terdaftar di course tersebut
            if course_name:
                # Cari course_id dari course_name di enrolled_courses
                course_match = next((c for c in enrolled_courses if course_name.lower() in c['fullname'].lower()), None)
                if not course_match:
                    return jsonify({"fulfillmentText": f"Kamu tidak terdaftar di kursus '{course_name}'."})
                course_ids = [course_match['id']]
            else:
                # Kalau tidak menyebut course, ambil semua course yang user ikuti
                course_ids = [c['id'] for c in enrolled_courses]

            # Query tugas yang sedang open untuk course_id yang valid
            format_strings = ','.join(['%s'] * len(course_ids))
            query_tugas = f"""
                SELECT c.fullname, a.name, a.allowsubmissionsfromdate, a.duedate
                FROM mdl_assign a
                JOIN mdl_course c ON c.id = a.course
                WHERE a.allowsubmissionsfromdate <= %s AND a.duedate >= %s
                AND a.course IN ({format_strings})
            """
            params_tugas = [now, now] + course_ids
            cursor.execute(query_tugas, params_tugas)
            tugas = cursor.fetchall()

            # Query quiz yang sedang open untuk course_id yang valid
            query_kuis = f"""
                SELECT c.fullname, q.name, q.timeopen, q.timeclose
                FROM mdl_quiz q
                JOIN mdl_course c ON c.id = q.course
                WHERE q.timeopen <= %s AND q.timeclose >= %s
                AND q.course IN ({format_strings})
            """
            params_kuis = [now, now] + course_ids
            cursor.execute(query_kuis, params_kuis)
            kuis = cursor.fetchall()

            if not tugas and not kuis:
                return jsonify({"fulfillmentText": "Minggu ini tidak ada tugas atau kuis yang sedang dibuka di kursus yang kamu ikuti."})

            lines = ["📌 Tugas dan Kuis yang sedang dibuka minggu ini :", "──────────────────────"]
            for t in tugas:
                lines.append(f"📝 Tugas: {t['name']} ({t['fullname']})")
                lines.append(f"──────────────────────➡️ Dibuka: {format_tanggal_indonesia(t['allowsubmissionsfromdate'])}")
                lines.append("\u00A0" * 35)
                lines.append(f"⏰ Deadline: {format_tanggal_indonesia(t['duedate'])}")
                lines.append("──────────────────────")

            for q in kuis:
                lines.append(f"🧪 Kuis: {q['name']} ({q['fullname']})")
                lines.append(f"──────────────────────➡️ Dibuka: {format_tanggal_indonesia(q['timeopen'])}")
                lines.append("\u00A0" * 35)
                lines.append(f"⏰ Ditutup: {format_tanggal_indonesia(q['timeclose'])}")
                lines.append("──────────────────────")

            return jsonify({"fulfillmentText": "\n".join(lines)})

        except Exception as e:
            print("Gagal ambil tugas/kuis:", e)
            return jsonify({"fulfillmentText": "Terjadi kesalahan saat mengambil data tugas dan kuis."})
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    else:
        fulfillment_text = req.get("queryResult", {}).get("fulfillmentText", "")
        if not fulfillment_text:
            fulfillment_text = "Maaf, saya tidak mengerti pertanyaan Anda."

        return jsonify({"fulfillmentText": fulfillment_text})

if __name__ == '__main__':
    app.run(port=5000, debug=True)
