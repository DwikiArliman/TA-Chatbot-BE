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
    sql = """
    INSERT INTO mdl_chatbot_sessions (session_id, userid, token, created_at, updated_at)
    VALUES (%s, %s, %s, NOW(), NOW())
    ON DUPLICATE KEY UPDATE userid=%s, token=%s, updated_at=NOW()
    """
    cursor.execute(sql, (session_id, userid, token, userid, token))
    conn.commit()
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
    return f"{hari}, {dt.day:02d} {bulan} {dt.year} {dt.strftime('%H:%M')}"

def get_userid_from_token(token):
    for userid, t in USER_TOKENS.items():
        if t == token:
            return userid
    return None


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

def get_section_contents_by_name(token, course_id, section_name):
    try:
        # Ambil semua sections dalam course
        params = {
            "wstoken": token,
            "wsfunction": "core_course_get_contents",
            "moodlewsrestformat": "json",
            "courseid": course_id
        }
        response = requests.get(MOODLE_API_URL, params=params)
        response.raise_for_status()
        sections = response.json()

        for section in sections:
            if section.get("name", "").lower() == section_name.lower():
                hasil = []
                for mod in section.get("modules", []):
                    nama_modul = mod.get("name", "(tanpa judul)")
                    mod_type = mod.get("modname", "")

                    if mod_type == "assign":
                        # ambil tanggal jika ada
                        tanggal_info = ""
                        for content in mod.get("dates", []):
                            if content.get("label") == "Due date":
                                tanggal = content.get("timestamp")
                                tanggal_info = f" (Deadline: {format_tanggal_indonesia(tanggal)})"
                                break
                        hasil.append(f"Tugas: {nama_modul}{tanggal_info}")
                    elif mod_type == "resource" or mod_type == "folder" or mod_type == "url":
                        hasil.append(f"Materi: {nama_modul}")
                    else:
                        hasil.append(f"Lainnya: {nama_modul}")
                return hasil
        return None
    except Exception as e:
        print("Gagal ambil section content:", e)
        return None
    

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    session_id = data.get("session_id")
    userid = data.get("userid")
    token = data.get("token")

    if session_id and userid and token:
        simpan_session(session_id, userid, token)
        return jsonify({"status": "success", "message": "Login berhasil."})
    else:
        return jsonify({"status": "error", "message": "Login gagal, periksa data login."})

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
    userid = parameters.get("userid")

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
                cursor.execute("""
                    SELECT name, timestart FROM mdl_event
                    WHERE courseid = %s AND timestart BETWEEN %s AND %s AND visible = 1
                    ORDER BY timestart ASC
                """, (course_id, start_ts, end_ts))
            else:
                cursor.execute("""
                    SELECT name, timestart FROM mdl_event
                    WHERE timestart BETWEEN %s AND %s AND visible = 1
                    ORDER BY timestart ASC
                """, (start_ts, end_ts))

            rows = cursor.fetchall()

            if course_id:
                course_name = get_course_fullname_by_id(course_id)
                course_desc = f"mata kuliah '{course_name}'" if course_name else f"mata kuliah ID {course_id}"
            else:
                course_desc = "hari ini"

            if not rows:
                return jsonify({"fulfillmentText": f"Tidak ada jadwal ditemukan untuk {course_desc}."})

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

    else:
        fulfillment_text = req.get("queryResult", {}).get("fulfillmentText", "")
        if not fulfillment_text:
            fulfillment_text = "Maaf, saya tidak mengerti pertanyaan Anda."

        return jsonify({"fulfillmentText": fulfillment_text})



if __name__ == '__main__':
    app.run(port=5000, debug=True)
