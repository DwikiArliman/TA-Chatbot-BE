from datetime import datetime, timedelta
import mysql.connector
import os
import time
from urllib.parse import quote

# --- Konfigurasi Database ---
session_port = os.getenv("MYSQLPORT")
moodle_port = os.getenv("MOODLE_DB_PORT")

db_config_session = {
    'host': os.getenv("MYSQLHOST"),
    'user': os.getenv("MYSQLUSER"),
    'password': os.getenv("MYSQLPASSWORD"),
    'database': os.getenv("MYSQLDATABASE"),
    'port': int(session_port) if session_port else 4000,
    'ssl_ca': 'isrgrootx1.pem',
    'ssl_verify_cert': True
}

db_config_moodle = {
    'host': os.getenv("MOODLE_DB_HOST"),
    'user': os.getenv("MOODLE_DB_USER"),
    'password': os.getenv("MOODLE_DB_PASSWORD"),
    'database': os.getenv("MOODLE_DB_DATABASE"),
    'port': int(moodle_port) if moodle_port else 3306
}

# --- Fungsi Koneksi ---
def get_session_db_connection():
    return mysql.connector.connect(**db_config_session)

def get_moodle_db_connection():
    return mysql.connector.connect(**db_config_moodle)

# --- Variabel Global ---
MOODLE_URL = os.getenv("MOODLE_URL", "http://20.2.66.68")

# --- Fungsi Utilitas ---
def format_tanggal_indonesia(timestamp):
    if not timestamp: return "Tidak ada tanggal"
    dt = datetime.fromtimestamp(int(timestamp))
    hari_mapping = {'Monday':'Senin','Tuesday':'Selasa','Wednesday':'Rabu','Thursday':'Kamis','Friday':'Jumat','Saturday':'Sabtu','Sunday':'Minggu'}
    bulan_mapping = {'January':'Januari','February':'Februari','March':'Maret','April':'April','May':'Mei','June':'Juni','July':'Juli','August':'Agustus','September':'September','October':'Oktober','November':'November','December':'Desember'}
    hari = hari_mapping.get(dt.strftime('%A'), dt.strftime('%A'))
    bulan = bulan_mapping.get(dt.strftime('%B'), dt.strftime('%B'))
    return f"{hari}, {dt.day:02d} {bulan} {dt.year} Pukul: {dt.strftime('%H:%M')}"

def timer_decorator(func):
    """Decorator untuk mengukur dan mencetak waktu eksekusi sebuah fungsi."""
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        duration = end_time - start_time
        print(f"--- [PERF] Fungsi '{func.__name__}' selesai dalam {duration:.4f} detik ---")
        return result
    return wrapper

def format_tanggal(timestamp):
    """Mengembalikan format tanggal: Senin, 14 Juli 2025"""
    if not timestamp: return "Tidak ada tanggal"
    dt = datetime.fromtimestamp(int(timestamp))
    hari_mapping = {'Monday':'Senin','Tuesday':'Selasa','Wednesday':'Rabu','Thursday':'Kamis','Friday':'Jumat','Saturday':'Sabtu','Sunday':'Minggu'}
    bulan_mapping = {'January':'Januari','February':'Februari','March':'Maret','April':'April','May':'Mei','June':'Juni','July':'Juli','August':'Agustus','September':'September','October':'Oktober','November':'November','December':'Desember'}
    hari = hari_mapping.get(dt.strftime('%A'), dt.strftime('%A'))
    bulan = bulan_mapping.get(dt.strftime('%B'), dt.strftime('%B'))
    return f"{hari}, {dt.day:02d} {bulan} {dt.year}"

def format_waktu(timestamp):
    """Mengembalikan format waktu: 03:30"""
    if not timestamp: return ""
    dt = datetime.fromtimestamp(int(timestamp))
    return dt.strftime('%H:%M')

def get_today_timestamp_range():
    now = datetime.now()
    start = datetime(now.year, now.month, now.day)
    end = start + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())

# --- Fungsi-fungsi Logika Moodle ---
def simpan_session(session_id, userid, token):
    conn = None; cursor = None
    try:
        conn = get_session_db_connection()
        cursor = conn.cursor()
        sql = "INSERT INTO mdl_chatbot_sessions (session_id, userid, token) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE token = VALUES(token), updated_at = NOW()"
        cursor.execute(sql, (session_id, userid, token))
        conn.commit()
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

def get_user_session_data(session_id):
    conn = None; cursor = None
    try:
        conn = get_session_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT userid, token FROM mdl_chatbot_sessions WHERE session_id = %s", (session_id,))
        return cursor.fetchone()
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

def get_user_fullname(userid):
    conn = None; cursor = None
    try:
        conn = get_moodle_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT firstname, lastname FROM mdl_user WHERE id = %s", (userid,))
        user = cursor.fetchone()
        return f"{user['firstname']} {user['lastname']}".strip() if user else "Pengguna"
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

@timer_decorator
def get_jadwal(userid):
    conn = None; cursor = None
    try:
        conn = get_moodle_db_connection()
        cursor = conn.cursor(dictionary=True)
        now_ts = int(datetime.now().timestamp())
        end_ts = int((datetime.now() + timedelta(days=7)).timestamp())
        
        # --- QUERY YANG DIPERBARUI ---
        query = """
            SELECT name, timestart 
            FROM mdl_event
            WHERE 
                (
                    -- Ambil event pribadi milik user
                    (eventtype = 'user' AND userid = %s)
                    OR 
                    -- Ambil event dari mata kuliah yang diikuti user
                    (eventtype = 'course' AND courseid IN (
                        SELECT e.courseid 
                        FROM mdl_user_enrolments ue 
                        JOIN mdl_enrol e ON ue.enrolid = e.id
                        WHERE ue.userid = %s
                    ))
                )
                AND timestart BETWEEN %s AND %s
            ORDER BY timestart ASC 
            LIMIT 10
        """
        cursor.execute(query, (userid, userid, now_ts, end_ts))
        return cursor.fetchall()
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

@timer_decorator
def get_tugas_quiz_hari_ini(userid):
    conn = None; cursor = None
    try:
        conn = get_moodle_db_connection()
        cursor = conn.cursor(dictionary=True)
        start_ts, end_ts = get_today_timestamp_range()
        query = """
            (SELECT 'tugas' AS item_type, a.name, a.duedate, c.fullname AS course_name FROM mdl_assign a JOIN mdl_course c ON a.course = c.id JOIN mdl_enrol e ON e.courseid = c.id JOIN mdl_user_enrolments ue ON ue.enrolid = e.id WHERE a.duedate BETWEEN %s AND %s AND ue.userid = %s)
            UNION ALL
            (SELECT 'kuis' AS item_type, q.name, q.timeclose AS duedate, c.fullname AS course_name FROM mdl_quiz q JOIN mdl_course c ON q.course = c.id JOIN mdl_enrol e ON e.courseid = c.id JOIN mdl_user_enrolments ue ON ue.enrolid = e.id WHERE q.timeclose BETWEEN %s AND %s AND ue.userid = %s)
            ORDER BY duedate ASC LIMIT 10
        """
        cursor.execute(query, (start_ts, end_ts, userid, start_ts, end_ts, userid))
        return cursor.fetchall()
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

@timer_decorator
def get_tugas_quiz_minggu_ini(userid):
    conn = None; cursor = None
    try:
        conn = get_moodle_db_connection()
        cursor = conn.cursor(dictionary=True)
        today = datetime.now()
        start_of_week = (today - timedelta(days=today.weekday())).replace(hour=0, minute=0, second=0)
        end_of_week = (start_of_week + timedelta(days=6)).replace(hour=23, minute=59, second=59)
        start_ts = int(start_of_week.timestamp())
        end_ts = int(end_of_week.timestamp())

        # --- QUERY YANG DIPERBARUI DENGAN FILTER VISIBILITY ---
        query = """
            (
                SELECT 'tugas' AS item_type, a.name, a.duedate, c.fullname AS course_name 
                FROM mdl_assign a 
                JOIN mdl_course c ON a.course = c.id
                JOIN mdl_course_modules cm ON cm.instance = a.id AND cm.module = (SELECT id FROM mdl_modules WHERE name = 'assign')
                JOIN mdl_enrol e ON e.courseid = c.id 
                JOIN mdl_user_enrolments ue ON ue.enrolid = e.id 
                WHERE a.duedate BETWEEN %s AND %s AND ue.userid = %s AND cm.visible = 1
            )
            UNION ALL
            (
                SELECT 'kuis' AS item_type, q.name, q.timeclose AS duedate, c.fullname AS course_name 
                FROM mdl_quiz q 
                JOIN mdl_course c ON q.course = c.id 
                JOIN mdl_course_modules cm ON cm.instance = q.id AND cm.module = (SELECT id FROM mdl_modules WHERE name = 'quiz')
                JOIN mdl_enrol e ON e.courseid = c.id 
                JOIN mdl_user_enrolments ue ON ue.enrolid = e.id 
                WHERE q.timeclose BETWEEN %s AND %s AND ue.userid = %s AND cm.visible = 1
            )
            ORDER BY duedate ASC 
            LIMIT 15
        """
        cursor.execute(query, (start_ts, end_ts, userid, start_ts, end_ts, userid))
        items = cursor.fetchall()
        
        if not items: return "Tidak ada tugas atau kuis yang terlihat dengan deadline pekan ini."
        reply_lines = ["Berikut adalah daftar tugas dan kuis untuk minggu ini:", ""]
        for item in items:
            emoji = "📝" if item['item_type'] == 'tugas' else "🧪"
            reply_lines.append(f"{emoji} {item['name']} ({item['course_name']})")
            reply_lines.append(f"   ⏰ Deadline: {format_tanggal_indonesia(item['duedate'])}")
            reply_lines.append("")
        return "\n".join(reply_lines)
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

@timer_decorator
def get_dosen_info_for_mahasiswa(student_userid, partial_course_name):
    conn = None; cursor = None
    try:
        conn = get_moodle_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, fullname FROM mdl_course WHERE fullname LIKE %s LIMIT 1", (f"%{partial_course_name}%",))
        course = cursor.fetchone()
        if not course: return f"Maaf, mata kuliah '{partial_course_name}' tidak ditemukan."
        
        cursor.execute("SELECT COUNT(ue.id) AS count FROM mdl_user_enrolments ue JOIN mdl_enrol e ON ue.enrolid = e.id WHERE ue.userid = %s AND e.courseid = %s", (student_userid, course['id']))
        if not cursor.fetchone()['count'] > 0: return f"Maaf, Anda tidak terdaftar di mata kuliah '{course['fullname']}'."

        sql_find_teachers = """
            SELECT u.firstname, u.lastname FROM mdl_user u
            JOIN mdl_role_assignments ra ON ra.userid = u.id JOIN mdl_context ctx ON ctx.id = ra.contextid
            WHERE ctx.instanceid = %s AND ctx.contextlevel = 50 AND ra.roleid IN (SELECT id FROM mdl_role WHERE shortname IN ('teacher', 'editingteacher'))
            ORDER BY u.lastname, u.firstname LIMIT 5
        """
        cursor.execute(sql_find_teachers, (course['id'],))
        teachers = cursor.fetchall()
        if not teachers: return f"Tidak ada dosen yang ditugaskan untuk mata kuliah '{course['fullname']}'."
        teacher_names = [f"👤 {t['firstname']} {t['lastname']}" for t in teachers]
        return f"Dosen untuk mata kuliah {course['fullname']} adalah:\n" + "\n".join(teacher_names)
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

@timer_decorator
def get_dosen_profile(partial_teacher_name):
    conn = None; cursor = None
    try:
        conn = get_moodle_db_connection()
        cursor = conn.cursor(dictionary=True)
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
        
@timer_decorator
def get_timeline_kegiatan(userid, limit=7, offset=0):
    conn = None; cursor = None
    try:
        #print("--- [DIAGNOSTIK] 1. Memulai fungsi get_timeline_kegiatan ---")
        
        #print("--- [DIAGNOSTIK] 2. Mencoba terhubung ke database Moodle... ---")
        conn = get_moodle_db_connection()
        #print("--- [DIAGNOSTIK] 3. KONEKSI BERHASIL ---")
        
        cursor = conn.cursor(dictionary=True)
        
        now_ts = int(datetime.now().timestamp())
        end_ts = int((datetime.now() + timedelta(days=90)).timestamp())
        query = """
            (SELECT 'tugas' AS item_type, a.name, a.duedate, c.fullname AS course_name FROM mdl_assign a JOIN mdl_course c ON a.course = c.id JOIN mdl_enrol e ON e.courseid = c.id JOIN mdl_user_enrolments ue ON ue.enrolid = e.id WHERE a.duedate BETWEEN %s AND %s AND ue.userid = %s)
            UNION ALL
            (SELECT 'kuis' AS item_type, q.name, q.timeclose AS duedate, c.fullname AS course_name FROM mdl_quiz q JOIN mdl_course c ON q.course = c.id JOIN mdl_enrol e ON e.courseid = c.id JOIN mdl_user_enrolments ue ON ue.enrolid = e.id WHERE q.timeclose BETWEEN %s AND %s AND ue.userid = %s)
            ORDER BY duedate ASC LIMIT %s OFFSET %s
        """
        
        #print("--- [DIAGNOSTIK] 4. Mencoba menjalankan query SQL... ---")
        cursor.execute(query, (now_ts, end_ts, userid, now_ts, end_ts, userid, limit, offset))
        #print("--- [DIAGNOSTIK] 5. QUERY BERHASIL DIJALANKAN ---")

        items = cursor.fetchall()
        #print(f"--- [DIAGNOSTIK] 6. Mengambil {len(items)} baris data ---")

        if not items: return "Tidak ada kegiatan (tugas/kuis) yang akan datang dalam 90 hari ke depan."
        reply_lines = [f"🗓️ Timeline Kegiatan Anda ({limit} berikutnya):", ""]
        for item in items:
            emoji = "📝" if item['item_type'] == 'tugas' else "🧪"
            reply_lines.append(f"{emoji} {item['name']} (di {item['course_name']})")
            reply_lines.append(f"   ⏰ Deadline: {format_tanggal_indonesia(item['duedate'])}")
            reply_lines.append("")
        return "\n".join(reply_lines)
    except Exception as e:
        print(f"--- [DIAGNOSTIK] ERROR TERJADI: {e}")
        return "Terjadi kesalahan saat memproses data timeline."
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()
        #print("--- [DIAGNOSTIK] 7. Fungsi selesai dan koneksi ditutup ---")

@timer_decorator
def get_materi_matkul(userid, partial_materi_name):
    conn = None; cursor = None
    try:
        conn = get_moodle_db_connection()
        cursor = conn.cursor(dictionary=True)
        #query = "SELECT f.contextid, f.component, f.filearea, f.itemid, f.filename, r.name AS resource_name, c.fullname AS course_name FROM mdl_files f JOIN mdl_context ctx ON f.contextid = ctx.id JOIN mdl_course_modules cm ON ctx.instanceid = cm.id AND ctx.contextlevel = 70 JOIN mdl_resource r ON cm.instance = r.id JOIN mdl_course c ON cm.course = c.id JOIN mdl_enrol e ON e.courseid = c.id JOIN mdl_user_enrolments ue ON ue.enrolid = e.id WHERE ue.userid = %s AND r.name LIKE %s AND f.component = 'mod_resource' AND f.filearea = 'content' AND f.filename != '.' AND (f.filename LIKE '%.pdf' OR f.filename LIKE '%.ppt' OR f.filename LIKE '%.pptx') LIMIT 1"
        query = """
            SELECT 
                f.contextid, f.component, f.filearea, f.itemid, f.filename, 
                r.name AS resource_name, c.fullname AS course_name 
            FROM mdl_files f 
            JOIN mdl_context ctx ON f.contextid = ctx.id 
            JOIN mdl_course_modules cm ON ctx.instanceid = cm.id AND ctx.contextlevel = 70 
            JOIN mdl_resource r ON cm.instance = r.id 
            JOIN mdl_course c ON cm.course = c.id 
            JOIN mdl_enrol e ON e.courseid = c.id 
            JOIN mdl_user_enrolments ue ON ue.enrolid = e.id 
            WHERE ue.userid = %s 
            AND r.name LIKE %s 
            AND f.component = 'mod_resource' 
            AND f.filearea = 'content' 
            AND f.filename != '.' 
            AND (
                f.filename LIKE '%.pdf' OR 
                f.filename LIKE '%.ppt' OR 
                f.filename LIKE '%.pptx' OR
                f.filename LIKE '%.doc' OR
                f.filename LIKE '%.docx'
            )
            LIMIT 1
        """
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

@timer_decorator
def get_materi_by_section(userid, course_name, section_name):
    conn = None; cursor = None
    try:
        conn = get_moodle_db_connection()
        cursor = conn.cursor(dictionary=True)
        #query = "SELECT f.contextid, f.component, f.filearea, f.itemid, f.filename, r.name AS resource_name, c.fullname AS course_name, cs.name AS section_name FROM mdl_files f JOIN mdl_context ctx ON f.contextid = ctx.id JOIN mdl_course_modules cm ON ctx.instanceid = cm.id AND ctx.contextlevel = 70 JOIN mdl_resource r ON cm.instance = r.id JOIN mdl_course c ON cm.course = c.id JOIN mdl_course_sections cs ON cm.section = cs.id JOIN mdl_enrol e ON e.courseid = c.id JOIN mdl_user_enrolments ue ON ue.enrolid = e.id WHERE ue.userid = %s AND c.fullname LIKE %s AND cs.name LIKE %s AND f.component = 'mod_resource' AND f.filearea = 'content' AND f.filename != '.' AND (f.mimetype = 'application/pdf' OR f.mimetype LIKE 'application/vnd.ms-powerpoint%') LIMIT 15"
        query = """
            SELECT 
                f.contextid, f.component, f.filearea, f.itemid, f.filename, 
                r.name AS resource_name, c.fullname AS course_name, cs.name AS section_name 
            FROM mdl_files f 
            JOIN mdl_context ctx ON f.contextid = ctx.id 
            JOIN mdl_course_modules cm ON ctx.instanceid = cm.id AND ctx.contextlevel = 70 
            JOIN mdl_resource r ON cm.instance = r.id 
            JOIN mdl_course c ON cm.course = c.id 
            JOIN mdl_course_sections cs ON cm.section = cs.id 
            JOIN mdl_enrol e ON e.courseid = c.id 
            JOIN mdl_user_enrolments ue ON ue.enrolid = e.id 
            WHERE ue.userid = %s 
            AND c.fullname LIKE %s 
            AND cs.name LIKE %s 
            AND f.component = 'mod_resource' 
            AND f.filearea = 'content' 
            AND f.filename != '.' 
            AND (
                f.filename LIKE '%.pdf' OR 
                f.filename LIKE '%.ppt' OR 
                f.filename LIKE '%.pptx' OR
                f.filename LIKE '%.doc' OR
                f.filename LIKE '%.docx'
            )   
            LIMIT 15
        """
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