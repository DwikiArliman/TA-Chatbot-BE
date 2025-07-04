from datetime import datetime, timedelta
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
import mysql.connector
import os # Untuk variabel lingkungan
from openai import OpenAI # Menggunakan library OpenAI, karena OpenRouter sering kompatibel
from dotenv import load_dotenv
from moodle_utils import *
import re

load_dotenv()
app = Flask(__name__)
CORS(app, supports_credentials=True, origins=[
    "http://localhost:5000", 
    "http://localhost", 
    "http://127.0.0.1", 
    "http://20.2.66.68"
])

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "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")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DEEPSEEK_MODEL = "deepseek-ai/deepseek-chat"

# Inisialisasi klien OpenAI dengan konfigurasi OpenRouter
client = OpenAI(
    base_url=OPENROUTER_BASE_URL,
    api_key=OPENROUTER_API_KEY,
)

# --- Konfigurasi Moodle dan Database (tetap sama) ---
USER_TOKENS = {
    "admin": "b7385120705a85eeb859e54c2ac5adad",
    "remigio": "01641dfdb56dfc7530a85de5179e2848",
    "adoria": "8cb1b92ed3d8490dcdf8ab67520cebb6",
    "kenny": "9117463d48feb4f59a23393868795dc2",
    "jordi": "0d4944592f2cdc3474af96e5a24c7dc5",
    "michael": "55a8c71c11abbc63d7111c5042e5c7b7",
    "ardyn": "35a4d3f5b54a62b25b025ceee3a519ea"
}

MOODLE_API_URL = "http://20.2.66.68/moodle/webservice/rest/server.php"

db_config_moodle = {
    'host': os.getenv("DB_HOST"),
    'user': os.getenv("DB_USER"),
    'password': os.getenv("DB_PASSWORD"),
    'database': os.getenv("DB_DATABASE"),
    'port': os.getenv("DB_PORT")
}

def call_deepseek_openrouter(user_input, userid=None):
    # Prompt bisa dimodifikasi agar mengenali keyword untuk memicu fungsi Moodle
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "http://20.2.66.68:5000",
        "X-Title": "Moodle AI Assistant"
    }

    prompt = f"""
    Kamu adalah asisten chatbot Moodle. Jika pertanyaan berisi hal seperti 'jadwal', 'tugas', atau 'pekan',
    arahkan untuk memanggil fungsi backend lokal, bukan menjawab dengan teks biasa.
    
    Pertanyaan: {user_input}
    """

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "Kamu adalah asisten AI untuk mahasiswa kampus."},
            {"role": "user", "content": prompt}
        ]
    }

    response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        return "Maaf, saya tidak bisa menjawab saat ini."

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

# --- Fungsi Baru: Memanggil Deepseek OpenRouter ---
def call_deepseek_openrouter(user_input, userid=None):
    # Prompt bisa dimodifikasi agar mengenali keyword untuk memicu fungsi Moodle
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "http://20.2.66.68:5000",
        "X-Title": "Moodle AI Assistant"
    }

    prompt = f"""
    Kamu adalah asisten chatbot Moodle. Jika pertanyaan berisi hal seperti 'jadwal', 'tugas', atau 'pekan',
    arahkan untuk memanggil fungsi backend lokal, bukan menjawab dengan teks biasa.
    
    Pertanyaan: {user_input}
    """

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "Kamu adalah asisten AI untuk mahasiswa kampus."},
            {"role": "user", "content": prompt}
        ]
    }

    response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        return "Maaf, saya tidak bisa menjawab saat ini."

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

def get_user_id_from_session(session_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT userid FROM mdl_chatbot_sessions WHERE session_id = %s", (session_id,))
        row = cursor.fetchone()
        return row['userid'] if row else None
    except Exception as e:
        print("Error get_user_id_from_session:", e)
        return None
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

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

# --- Existing Endpoints ---

@app.route('/get_moodle_user_id', methods=['POST'])
def get_moodle_user_id():
    """
    Endpoint untuk frontend agar bisa mengambil Moodle User ID.
    Frontend harus mengirim 'token' yang relevan (token dari sesi Moodle user).
    """
    data = request.get_json()
    token = data.get('token')

    if not token:
        return jsonify({"status": "error", "message": "Token harus disediakan."}), 400

    userid = get_userid_from_token(token)
    if userid:
        return jsonify({"status": "success", "userid": userid}), 200
    else:
        return jsonify({"status": "error", "message": "User ID tidak ditemukan untuk token ini. Token mungkin tidak valid atau kedaluwarsa."}), 404

@app.route('/login', methods=['POST'])
def login():
    print("\n--- MENCOBA MEMPROSES REQUEST DI /login ---")

    # Langkah 1: Coba ambil data JSON dengan aman
    try:
        data = request.get_json()
        if data is None:
            print("[LOGIN_ERROR] Request tidak berisi data JSON atau header Content-Type salah.")
            return jsonify({'status': 'error', 'message': 'Invalid JSON request. Pastikan header Content-Type adalah application/json.'}), 400
    except Exception as e:
        print(f"[LOGIN_ERROR] Gagal mem-parsing JSON: {e}")
        return jsonify({'status': 'error', 'message': f'Failed to parse JSON: {e}'}), 400

    # Langkah 2: Jika berhasil, cetak data yang diterima untuk debugging
    print("--- DATA DITERIMA DI /login ---")
    print(data)

    # Langkah 3: Ekstrak data dan lanjutkan proses (sekarang aman)
    conn = None # Inisialisasi di luar try agar bisa diakses di finally
    try:
        # Gunakan .get() untuk keamanan, atau biarkan seperti ini jika semua wajib ada
        session_id = data['session_id']
        userid = data['userid']
        token = data['token']

        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Simpan ke mdl_chatbot_sessions
        cursor.execute("""
            INSERT INTO mdl_chatbot_sessions (session_id, userid, token, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE
                token = VALUES(token),
                updated_at = NOW()
            """, (session_id, userid, token))
        
        conn.commit()

        print("[LOGIN_SUCCESS] Data login berhasil disimpan ke database.")
        return jsonify({'status': 'success', 'message': 'Login data saved successfully.'})

    except KeyError as e:
        # Error ini terjadi jika 'session_id', 'userid', atau 'token' tidak ada di JSON
        print(f"[LOGIN_ERROR] Key yang wajib ada tidak ditemukan di JSON: {e}")
        return jsonify({'status': 'error', 'message': f'Missing required key in JSON payload: {e}'}), 400
    except Exception as e:
        # Error lain, misalnya error database
        print(f"[LOGIN_ERROR] Terjadi error saat memproses data: {e}")
        if conn:
            conn.rollback() # Batalkan transaksi jika terjadi error
        return jsonify({'status': 'error', 'message': f'An error occurred: {e}'}), 500
    finally:
        # Pastikan koneksi selalu ditutup
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

@app.route('/send-token', methods=['POST'])
def send_token():
    data = request.get_json()
    session_id = data.get("session_id")
    token = data.get("token")

    if not session_id or not token:
        return jsonify({"status": "error", "message": "session_id dan token harus diberikan"}), 400

    userid = get_userid_from_token(token)
    if not userid:
        return jsonify({"status": "error", "message": "Token tidak valid atau tidak dapat mengambil user ID dari Moodle."}), 400

    simpan_session(session_id, userid, token)
    return jsonify({"status": "success", "message": "Token disimpan dan session berhasil dihubungkan.", "userid": userid})

@app.route('/chat', methods=['POST'])
def chat():
    print("\n--- MENCOBA MEMPROSES REQUEST DI /chat ---")

    # Langkah 1: Ambil data JSON dengan aman dari request
    try:
        data = request.get_json()
        if data is None:
            print("[CHAT_ERROR] Request tidak berisi data JSON atau header Content-Type salah.")
            return jsonify({'reply': 'Error: Format request tidak valid.'}), 400
    except Exception as e:
        print(f"[CHAT_ERROR] Gagal mem-parsing JSON: {e}")
        return jsonify({'reply': f'Error: Gagal memproses request: {e}'}), 400
    
    # Langkah 2: Cetak data yang berhasil didapat untuk debugging
    print("--- DATA DITERIMA DI /chat ---")
    print(data)

    # Langkah 3: Ekstrak data dan panggil fungsi helper untuk validasi sesi dari DB
    session_id = data.get("session_id", "")
    message = data.get("message", "")
    
    # Panggil fungsi helper yang benar yang sudah kita definisikan sebelumnya
    user_session = get_user_session_data(session_id)

    # Langkah 4: Validasi sesi. Jika tidak valid, hentikan proses di sini.
    if not user_session:
        print(f"[CHAT_DENIED] Sesi tidak ditemukan untuk session_id: '{session_id}'")
        return jsonify({"reply": "Sesi Anda tidak valid atau telah berakhir. Silakan login kembali."})

    # Langkah 5: Ekstrak data user dan lanjutkan ke logika utama chatbot
    try:
        userid = user_session['userid']
        token = user_session['token'] # Token ini bisa digunakan untuk API Moodle lain jika perlu
        print(f"[CHAT_SUCCESS] Validated userid={userid} for session_id='{session_id}'")

        # --- Logika Utama Chatbot Anda ---
        sapaan_awal = ["hai", "halo", "assalamualaikum", "hi", "hello", "pagi", "siang", "malam"]
        if any(greet in message.lower() for greet in sapaan_awal):
            nama = get_user_fullname(userid)
            return jsonify({"reply": f"Hai {nama}, ada yang bisa saya bantu hari ini?"})

        if "jadwal" in message.lower():
            rows = get_jadwal(userid)
            if not rows:
                return jsonify({"reply": "Tidak ada jadwal ditemukan untuk Anda."})
            teks = "\n".join([f"📅 {row['name']} - {format_tanggal_indonesia(row['timestart'])}" for row in rows])
            return jsonify({"reply": teks})

        elif "tugas hari ini" in message.lower():
            # Panggil fungsi yang sudah direvisi
            tugas = get_tugas_quiz_hari_ini(userid) 
            
            if not tugas:
                return jsonify({"reply": "Tidak ada tugas atau kuis dengan deadline hari ini. Selamat bersantai!"})

            reply = ["📌 Deadline Hari Ini:"]
            for t in tugas:
                # Gunakan emoji yang berbeda berdasarkan item_type
                emoji = "📝" if t['item_type'] == 'tugas' else "🧪"
                
                # PERBAIKAN: Gunakan key 'name' yang benar
                reply.append(f"{emoji} {t['name']} ({t['course_name']})")
                reply.append(f"   ⏰ {format_tanggal_indonesia(t['duedate'])}")
                reply.append("") # Tambah baris kosong untuk kerapian

            return jsonify({"reply": "\n".join(reply)})
        
        elif "tugas minggu ini" in message.lower() or "tugas pekan ini" in message.lower():
            # Cukup panggil fungsi dan simpan hasilnya (yang sudah berupa string)
            reply_text = get_tugas_quiz_minggu_ini(userid)
            
            # Langsung kembalikan teks tersebut sebagai balasan
            return jsonify({"reply": reply_text})

        
        elif "siapa dosen" in message.lower():
            course_name = message.lower().replace("siapa dosen", "").strip()
            if not course_name:
                reply = "Tolong sebutkan nama mata kuliahnya. Contoh: 'siapa dosen sistem basis data'"
            else:
                dosen_data = get_dosen_info_for_mahasiswa(userid, course_name)

                if dosen_data.startswith("Dosen untuk"):
                    reply = dosen_data
                else:
                    reply = f"Tidak dapat menemukan dosen untuk mata kuliah '{course_name}'. {dosen_data}"

            return jsonify({"reply": reply})
        
        elif "info dosen" in message.lower():
            teacher_name = message.lower().replace("info dosen", "").replace("?", "").strip()
            
            if not teacher_name:
                reply = "Tolong sebutkan nama dosen yang ingin dicari. Contoh: 'info dosen Bartho Kols"
            else:
                reply = get_dosen_profile(teacher_name)
            
            return jsonify({"reply": reply})
        
        elif "timeline" in message.lower():
            # Panggil fungsi baru untuk mendapatkan timeline
            reply_text = get_timeline_kegiatan(userid)
            
            # Langsung kembalikan teks yang sudah diformat oleh fungsi tersebut
            return jsonify({"reply": reply_text})
        
        elif "materi" in message.lower() or "lihat file" in message.lower() or "lihat materi" in message.lower():
            # Coba parsing untuk permintaan spesifik (contoh: "materi week 1 algoritma pemrograman")
            # Pola regex ini mencari kata seperti "week 1", "pekan 1", "bab 2", dll.
            match = re.search(r'(week|pekan|bab|sesi|pertemuan)\s*(\d+)\s*(.*)', message.lower(), re.IGNORECASE)

            if match:
                # Jika polanya cocok, ini adalah permintaan spesifik
                section_type = match.group(1) # "week", "pekan", dll.
                section_number = match.group(2) # "1", "2", dll.
                course_name = match.group(3).strip() # Sisa teks adalah nama mata kuliah

                # Gabungkan kembali nama section yang lengkap, contoh: "Week 1"
                full_section_name = f"{section_type.capitalize()} {section_number}"

                if not course_name:
                    reply_text = f"Tentu, materi untuk '{full_section_name}' dari mata kuliah apa yang ingin Anda lihat?"
                else:
                    # Panggil fungsi baru yang spesifik
                    reply_text = get_materi_by_section(userid, course_name, full_section_name)

            else:
                # Jika tidak ada pola section, anggap ini permintaan umum
                # --- PERBAIKAN LOGIKA PEMBERSIHAN ---
                keywords = [
                    "lihat materi tentang", "lihat file tentang", "materi tentang",
                    "lihat materi", "lihat file", "materi", "tentang", "dari", "file"
                ]
                # Membuat pola regex: ^\s*(keyword1|keyword2|...)\s*
                # Ini akan menghapus kata kunci HANYA jika ada di awal kalimat.
                pattern = r'^\s*(' + '|'.join(keywords) + r')\s*'
                
                # Bersihkan pesan dari kata kunci menggunakan regex
                materi_name = re.sub(pattern, '', message.lower(), flags=re.IGNORECASE).strip()

                if not materi_name:
                    reply_text = "Tentu, materi apa yang ingin Anda lihat? Contoh: 'materi pengenalan basis data' atau 'materi week 1 algoritma'"
                else:
                    # Panggil fungsi umum dengan nama materi yang sudah bersih
                    reply_text = get_materi_matkul(userid, materi_name)
            
            return jsonify({"reply": reply_text})

        # ... blok elif lainnya ...

        else:
            # Jika tidak ada keyword yang cocok, panggil AI generatif
            return jsonify({"reply": call_deepseek_openrouter(message, userid)})

    except Exception as e:
        # Menangkap error tak terduga selama pemrosesan logika chatbot
        print(f"[CHAT_ERROR] Terjadi error saat memproses logika chatbot: {e}")
        return jsonify({"reply": "Maaf, terjadi kesalahan internal saat memproses permintaan Anda."}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
