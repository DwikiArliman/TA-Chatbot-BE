from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import os
import requests
import re
from moodle_utils import *

# Muat environment variables dari file .env
load_dotenv()

app = Flask(__name__)
CORS(app, supports_credentials=True, origins=[
    "http://localhost:5000", 
    "http://localhost", 
    "http://127.0.0.1", 
    "http://20.2.66.68"
])

# Konfigurasi OpenRouter
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

def call_deepseek_openrouter(user_input: str, userid: str = None, max_retries: int = 3, retry_delay: int = 2):
    """
    Memanggil model AI generatif (DeepSeek) dengan mekanisme coba lagi (retry) jika gagal.

    Args:
        user_input (str): Pertanyaan dari pengguna.
        userid (str, optional): ID pengguna, saat ini tidak digunakan tapi disiapkan untuk pengembangan di masa depan.
        max_retries (int, optional): Jumlah maksimum percobaan ulang. Defaultnya adalah 3.
        retry_delay (int, optional): Jeda waktu (dalam detik) antar percobaan ulang. Defaultnya adalah 2.

    Returns:
        str: Jawaban dari AI atau pesan fallback jika semua percobaan gagal.
    """
    if not OPENROUTER_API_KEY:
        print("[AI_ERROR] Variabel environment OPENROUTER_API_KEY tidak diatur.")
        return "Maaf, konfigurasi asisten AI belum lengkap. Harap hubungi administrator."

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": MOODLE_URL,
        "X-Title": "Moodle AI Assistant"
    }

    # ✨ Penyempurnaan prompt:
    # Instruksi umum ditempatkan di 'system', dan pertanyaan pengguna langsung di 'user'.
    # Ini adalah praktik yang lebih baik dan sering memberikan hasil yang lebih konsisten.
    payload = {
        "model": "deepseek-ai/deepseek-chat",
        "messages": [
            {"role": "system", "content": "Kamu adalah asisten AI yang ramah dan sangat membantu untuk mahasiswa. Jawab semua pertanyaan terkait kegiatan perkuliahan mereka di Moodle dengan singkat, jelas, dan akurat."},
            {"role": "user", "content": user_input}
        ]
    }

    # ⚙️ Mekanisme coba lagi (retry)
    for attempt in range(max_retries):
        try:
            print(f"[AI_INFO] Menghubungi DeepSeek... (Percobaan {attempt + 1}/{max_retries})")
            response = requests.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=25  # Timeout sedikit lebih lama untuk koneksi yang lambat
            )
            # Ini akan memicu error (exception) jika status code adalah 4xx atau 5xx
            response.raise_for_status()

            # Jika berhasil, ekstrak pesan, kembalikan, dan hentikan fungsi
            return response.json()["choices"][0]["message"]["content"]

        except requests.exceptions.RequestException as e:
            print(f"[AI_WARNING] Gagal pada percobaan {attempt + 1}: {e}")
            # Jika ini adalah percobaan terakhir, loop akan berhenti dan fallback akan dijalankan
            if attempt < max_retries - 1:
                time.sleep(retry_delay)  # Tunggu sejenak sebelum mencoba lagi
            else:
                print(f"[AI_ERROR] Semua {max_retries} percobaan gagal. Menggunakan pesan fallback.")

    # Pesan fallback ini hanya akan dikembalikan jika semua percobaan dalam loop gagal
    return "Maaf, asisten AI sedang mengalami sedikit gangguan. Silakan coba lagi beberapa saat lagi atau gunakan tombol bantuan yang tersedia."

@app.route('/login', methods=['POST'])
def login():
    """Endpoint untuk menyimpan data sesi saat user login."""
    #print("\n--- MENCOBA MEMPROSES REQUEST DI /login ---")
    try:
        data = request.get_json()
        if data is None:
            return jsonify({'status': 'error', 'message': 'Invalid JSON request.'}), 400
        #print(f"--- DATA DITERIMA DI /login ---\n{data}")
        simpan_session(data['session_id'], data['userid'], data['token'])
        print("[LOGIN_SUCCESS] Data login berhasil disimpan.")
        return jsonify({'status': 'success', 'message': 'Login data saved successfully.'})
    except KeyError as e:
        print(f"[LOGIN_ERROR] Key yang wajib ada tidak ditemukan: {e}")
        return jsonify({'status': 'error', 'message': f'Missing required key: {e}'}), 400
    except Exception as e:
        print(f"[LOGIN_ERROR] Terjadi error: {e}")
        return jsonify({'status': 'error', 'message': f'An error occurred: {e}'}), 500

@app.route('/chat', methods=['POST'])
def chat():
    # ===== TAMBAHKAN PRINT INI UNTUK PEMBUKTIAN =====
    #print("--- CHAT ENDPOINT VERSI 1.1 DIAKSES (DENGAN OPTIMASI) ---")
    # ===============================================

    #print("\n--- MENCOBA MEMPROSES REQUEST DI /chat ---")
    try:
        data = request.get_json()
        if data is None:
            return jsonify({'reply': 'Error: Format request tidak valid.'}), 400
        #print(f"--- DATA DITERIMA DI /chat ---\n{data}")

        session_id = data.get("session_id", "")
        message = data.get("message", "").lower()
        
        user_session = get_user_session_data(session_id)
        if not user_session:
            print(f"[CHAT_DENIED] Sesi tidak ditemukan untuk session_id: '{session_id}'")
            return jsonify({"reply": "Sesi Anda tidak valid atau telah berakhir. Silakan login kembali."})

        userid = user_session['userid']
        print(f"[CHAT_SUCCESS] Validated userid={userid} for session_id='{session_id}'")

        # --- Logika Utama Chatbot ---
        sapaan_awal = ["hai", "halo", "assalamualaikum", "hi", "hello", "pagi", "siang", "malam"]
        if any(greet in message for greet in sapaan_awal):
            nama = get_user_fullname(userid)
            reply_text = f"Hai {nama}, ada yang bisa saya bantu?"

        elif "timeline" in message:
            reply_text = get_timeline_kegiatan(userid)

        # Di dalam file app.py, pada fungsi chat()

        elif "jadwal" in message:
            events = get_jadwal(userid)
            if not events:
                reply_text = "Tidak ada jadwal ditemukan untuk Anda dalam 7 hari ke depan."
            else:
                reply_lines = ["🗓️ Jadwal Anda (7 hari ke depan):", ""]
                for event in events:
                    reply_lines.append(f" 📝 {event['name']}")
                    # Menggunakan fungsi format_tanggal yang baru
                    reply_lines.append(f"  🗓️ Waktu: {format_tanggal(event['timestart'])}")
                    # Menambahkan baris Pukul dengan fungsi format_waktu
                    reply_lines.append(f"  ⏰ Pukul: {format_waktu(event['timestart'])}")
                    reply_lines.append("") # Baris kosong sebagai pemisah
                
                reply_text = "\n".join(reply_lines)

        elif "tugas hari ini" in message:
            items = get_tugas_quiz_hari_ini(userid)
            if not items:
                reply_text = "Tidak ada tugas atau kuis dengan deadline hari ini. Selamat bersantai!"
            else:
                reply_lines = [" Tugas dan Kuis Hari Ini:"]
                for item in items:
                    emoji = "📝" if item['item_type'] == 'tugas' else "🧪"
                    reply_lines.append(f"{emoji} {item['name']} ({item['course_name']}) - ⏰ {format_tanggal_indonesia(item['duedate'])}")
                reply_text = "\n".join(reply_lines)
        
        elif "tugas minggu ini" in message or "tugas pekan ini" in message:
            reply_text = get_tugas_quiz_minggu_ini(userid)
        
        elif "siapa dosen" in message:
            course_name = message.replace("siapa dosen", "").strip()
            if not course_name:
                reply_text = "Tolong sebutkan nama mata kuliahnya. Contoh: 'siapa dosen sistem basis data'"
            else:
                reply_text = get_dosen_info_for_mahasiswa(userid, course_name)
        
        elif "info dosen" in message:
            teacher_name = message.replace("info dosen", "").replace("?", "").strip()
            if not teacher_name:
                reply_text = "Tolong sebutkan nama dosen yang ingin dicari. Contoh: 'info dosen Bartho Kols'"
            else:
                reply_text = get_dosen_profile(teacher_name)
        
        elif "materi" in message or "lihat file" in message:
            match = re.search(r'(week|pekan|bab|sesi|pertemuan)\s*(\d+)\s*(.*)', message, re.IGNORECASE)
            if match:
                section_type, section_number, course_name = match.groups()
                full_section_name = f"{section_type.capitalize()} {section_number}"
                if not course_name.strip():
                    reply_text = f"Tentu, materi untuk '{full_section_name}' dari mata kuliah apa yang ingin Anda lihat?"
                else:
                    reply_text = get_materi_by_section(userid, course_name.strip(), full_section_name)
            else:
                keywords = ["lihat materi tentang", "lihat file tentang", "materi tentang", "lihat materi", "lihat file", "materi", "tentang", "dari", "file"]
                pattern = r'^\s*(' + '|'.join(keywords) + r')\s*'
                materi_name = re.sub(pattern, '', message, flags=re.IGNORECASE).strip()
                if not materi_name or len(materi_name) < 3:
                    reply_text = "Tentu, materi spesifik apa yang ingin Anda cari? Contoh : lihat materi week 1 Algoritma Pemrograman."
                else:
                    reply_text = get_materi_matkul(userid, materi_name)
        
        else:
            reply_text = call_deepseek_openrouter(message, userid)

        return jsonify({"reply": reply_text})

    except Exception as e:
        print(f"[CHAT_ERROR] Terjadi error tak terduga: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"reply": "Maaf, terjadi kesalahan internal saat memproses permintaan Anda."}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)