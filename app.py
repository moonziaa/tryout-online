import streamlit as st
import pandas as pd
import time
import json
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Try Out TKA SD Online", page_icon="☁️", layout="wide")

# --- CSS CUSTOM ---
st.markdown("""
<style>
    [data-testid="stAppViewContainer"] { background-color: #f8f9fa; color: #000000; }
    [data-testid="stSidebar"] { background-color: #e3f2fd; }
    [data-testid="stSidebar"] * { color: #0d47a1 !important; }
    .stButton>button { color: white !important; background: linear-gradient(to right, #1565c0, #42a5f5); border: none; }
    .timer-box { font-size: 24px; font-weight: bold; color: #d32f2f !important; text-align: center; border: 2px solid #d32f2f; padding: 10px; border-radius: 10px; background-color: #ffebee; }
</style>
""", unsafe_allow_html=True)

# --- KONEKSI FIREBASE ---
@st.cache_resource
def get_db():
    if not firebase_admin._apps:
        # Kodingan ini otomatis mencari settingan yang Ibu taruh di Website Streamlit (Secrets)
        # Jadi tidak perlu paste kode aneh-aneh di sini.
        key_dict = json.loads(json.dumps(dict(st.secrets["firebase"])))
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

try:
    db = get_db()
except Exception as e:
    st.error("Belum terkoneksi ke Database. Harap setting Secrets di Streamlit Cloud sesuai panduan.")
    st.stop()

# --- FUNGSI DATABASE ---
def get_questions(mapel):
    docs = db.collection('questions').where('mapel', '==', mapel).stream()
    questions = []
    for doc in docs:
        d = doc.to_dict()
        d['id'] = doc.id
        questions.append(d)
    if questions:
        return pd.DataFrame(questions).sample(frac=1).head(30)
    return pd.DataFrame()

# --- LOGIN ---
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False

def login_page():
    st.title("☁️ Login Try Out Online")
    u = st.text_input("Username"); p = st.text_input("Password", type="password")
    if st.button("Masuk"):
        if u == "admin" and p == "admin123":
            st.session_state.update({'logged_in': True, 'role': 'admin', 'nama': 'Admin', 'username': 'admin'})
            st.rerun()
        else:
            # Cek ke Firebase
            users = db.collection('users').where('username', '==', u).where('password', '==', p).stream()
            found = False
            for user in users:
                data = user.to_dict()
                st.session_state.update({'logged_in': True, 'role': 'siswa', 'nama': data['nama_lengkap'], 'username': data['username']})
                found = True
                st.rerun()
            if not found: st.error("Salah password/username")

# --- DASHBOARD ADMIN ---
def admin_page():
    st.sidebar.button("Keluar", on_click=lambda: st.session_state.clear())
    st.title("Halaman Guru (Admin)")
    
    tab1, tab2, tab3 = st.tabs(["Nilai Siswa", "Upload Soal", "Buat Akun Siswa"])
    
    with tab1:
        if st.button("Refresh Data Nilai"): st.rerun()
        docs = db.collection('results').order_by('tanggal', direction=firestore.Query.DESCENDING).stream()
        data = [d.to_dict() for d in docs]
        if data:
            df = pd.DataFrame(data)
            st.dataframe(df)
            st.download_button("Download CSV", df.to_csv().encode('utf-8'), "nilai.csv")
        else: st.info("Belum ada nilai masuk.")

    with tab2:
        st.info("Upload CSV untuk menambah soal ke Cloud Database.")
        up = st.file_uploader("CSV Soal", type=['csv'])
        if up and st.button("Proses Upload"):
            df = pd.read_csv(up)
            prog = st.progress(0)
            for i, row in df.iterrows():
                # Simpan per baris ke Firebase
                item = row.to_dict()
                # Pastikan format JSON valid string
                db.collection('questions').add(item)
                prog.progress((i+1)/len(df))
            st.success("Selesai upload!")

    with tab3:
        with st.form("tambah_siswa"):
            u = st.text_input("Username"); p = st.text_input("Password"); n = st.text_input("Nama")
            if st.form_submit_button("Simpan Akun"):
                db.collection('users').document(u).set({'username': u, 'password': p, 'nama_lengkap': n})
                st.success(f"Siswa {n} berhasil dibuat!")

# --- DASHBOARD SISWA ---
def student_page():
    st.sidebar.write(f"Login: {st.session_state['nama']}")
    st.sidebar.button("Keluar", on_click=lambda: st.session_state.clear())
    
    if 'exam_running' not in st.session_state: st.session_state['exam_running'] = False

    if not st.session_state['exam_running']:
        col1, col2 = st.columns(2)
        if col1.button("Matematika"): start_exam("Matematika")
        if col2.button("B. Indonesia"): start_exam("Bahasa Indonesia")
    else:
        exam_interface()

def start_exam(mapel):
    q = get_questions(mapel)
    if q.empty: st.error("Soal kosong."); return
    st.session_state.update({'exam_running': True, 'mapel': mapel, 'q_data': q, 'start': time.time(), 'ans': {}})
    st.rerun()

def exam_interface():
    # Timer 75 menit
    rem = (75*60) - (time.time() - st.session_state['start'])
    if rem <= 0: submit_exam(); return
    m, s = divmod(int(rem), 60)
    st.sidebar.markdown(f"<div class='timer-box'>{m:02d}:{s:02d}</div>", unsafe_allow_html=True)
    if st.sidebar.button("Kumpulkan"): submit_exam()

    st.header(f"Soal {st.session_state['mapel']}")
    for idx, row in st.session_state['q_data'].iterrows():
        st.write(f"**{idx+1}. {row['pertanyaan']}**")
        opsi = json.loads(row['opsi'])
        key = f"q_{row['id']}"
        
        if row['tipe'] == 'single':
            st.radio("Jawab:", opsi, key=key)
        elif row['tipe'] == 'complex':
            st.multiselect("Pilih:", opsi, key=key)
        elif row['tipe'] == 'category':
            for o in opsi: st.radio(o, ["Benar", "Salah"], key=f"{key}_{o}", horizontal=True)
        
        if key in st.session_state: st.session_state['ans'][row['id']] = st.session_state[key]
        st.divider()

def submit_exam():
    score = 0; detail = []
    for idx, row in st.session_state['q_data'].iterrows():
        ans = st.session_state['ans'].get(row['id'])
        kunci = json.loads(row['kunci_jawaban'])
        # Logika penilaian sederhana
        correct = False
        if row['tipe'] == 'single' and ans == kunci: correct = True
        elif row['tipe'] == 'complex' and ans and set(ans) == set(kunci): correct = True
        elif row['tipe'] == 'category' and ans == kunci: correct = True
        
        if correct: score += 1
        detail.append({'soal': row['pertanyaan'], 'benar': correct})
    
    final = (score / len(st.session_state['q_data'])) * 100
    
    # Simpan ke Firebase
    data = {
        'username': st.session_state['username'],
        'mapel': st.session_state['mapel'],
        'skor': final,
        'tanggal': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'detail': json.dumps(detail)
    }
    db.collection('results').add(data)
    
    st.session_state['exam_running'] = False
    st.success(f"Nilai tersimpan: {final}")
    time.sleep(3)
    st.rerun()

# --- MAIN LOOP ---
if not st.session_state['logged_in']: login_page()
else:
    if st.session_state['role'] == 'admin': admin_page()
    else: student_page()