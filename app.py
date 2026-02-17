import streamlit as st
import pandas as pd
import time
import json
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Try Out TKA SD Online", page_icon="📝", layout="wide")

# --- CSS CUSTOM (JURUS PAMUNGKAS - ANTI TOMBOL) ---
st.markdown("""
<style>
    /* 1. HILANGKAN SELURUH HEADER ATAS (Garis, Tombol, Profil) */
    header {
        visibility: hidden !important;
        height: 0px !important;
        background: transparent !important;
    }
    
    /* 2. HILANGKAN TOMBOL-TOMBOL SPESIFIK */
    .stAppDeployButton { display: none !important; }
    [data-testid="stHeader"] { display: none !important; }
    [data-testid="stToolbar"] { display: none !important; }
    [data-testid="stStatusWidget"] { display: none !important; }
    [data-testid="baseButton-header"] { display: none !important; }
    
    /* 3. GESER KONTEN KE ATAS (Supaya tidak ada ruang kosong bekas header) */
    .block-container {
        padding-top: 1rem !important;
        margin-top: -3rem !important; /* Tarik paksa ke atas */
    }

    /* 4. HILANGKAN FOOTER */
    footer { display: none !important; visibility: hidden !important; }
    #MainMenu { display: none !important; }

    /* --- STYLE TAMPILAN APLIKASI --- */
    [data-testid="stAppViewContainer"] { background-color: #f8f9fa; color: #000000; }
    [data-testid="stSidebar"] { background-color: #e3f2fd; }
    .stButton>button { color: white !important; background: linear-gradient(to right, #1565c0, #42a5f5); border: none; font-weight: bold; }
    .timer-box { font-size: 24px; font-weight: bold; color: #d32f2f !important; text-align: center; border: 2px solid #d32f2f; padding: 10px; border-radius: 10px; background-color: #ffebee; }
    .correct { color: green; font-weight: bold; }
    .wrong { color: red; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# --- KONEKSI FIREBASE ---
@st.cache_resource
def get_db():
    if not firebase_admin._apps:
        key_dict = json.loads(json.dumps(dict(st.secrets["firebase"])))
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    return firestore.client()

try:
    db = get_db()
except:
    st.error("Koneksi Database Gagal. Cek Secrets di Streamlit.")
    st.stop()

# --- FUNGSI UTILITY ---
def load_questions(mapel):
    docs = db.collection('questions').where('mapel', '==', mapel).stream()
    data = []
    for doc in docs:
        d = doc.to_dict()
        d['id'] = doc.id
        data.append(d)
    if data: return pd.DataFrame(data).sample(frac=1).head(30)
    return pd.DataFrame()

# --- HALAMAN LOGIN ---
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False

def login_page():
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.title("🎓 Login Try Out")
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("Masuk"):
            if u == "admin" and p == "admin123":
                st.session_state.update({'logged_in':True, 'role':'admin', 'nama':'Guru Admin', 'username':'admin'})
                st.rerun()
            else:
                users = db.collection('users').where('username','==',u).where('password','==',p).stream()
                found = False
                for user in users:
                    d = user.to_dict()
                    st.session_state.update({'logged_in':True, 'role':'siswa', 'nama':d['nama_lengkap'], 'username':d['username']})
                    found = True; st.rerun()
                if not found: st.error("Username/Password salah")

# --- DASHBOARD ADMIN ---
def admin_page():
    st.sidebar.button("Keluar", on_click=lambda: st.session_state.clear())
    st.title("Halaman Guru (Admin)")
    
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Nilai", "✍️ Input Manual", "📂 Upload Excel/CSV", "👥 Siswa"])
    
    # 1. LIHAT NILAI
    with tab1:
        if st.button("Refresh Nilai"): st.rerun()
        docs = db.collection('results').order_by('tanggal', direction=firestore.Query.DESCENDING).stream()
        data = [d.to_dict() for d in docs]
        if data:
            df = pd.DataFrame(data)
            st.dataframe(df[['tanggal', 'nama', 'mapel', 'skor']])
            st.download_button("Download Excel", df.to_csv().encode('utf-8'), "nilai.csv")
        else: st.info("Belum ada data.")

    # 2. INPUT SOAL MANUAL
    with tab2:
        st.subheader("Tambah Soal Tanpa Ribet")
        with st.form("input_manual"):
            col_a, col_b = st.columns(2)
            with col_a:
                in_mapel = st.selectbox("Mata Pelajaran", ["Matematika", "Bahasa Indonesia"])
                in_topik = st.text_input("Topik (misal: Pecahan/Puisi)")
            with col_b:
                in_tipe = st.selectbox("Tipe Soal", ["Pilihan Ganda (1 Jawaban)", "Pilihan Ganda Kompleks (>1 Jawaban)", "Benar/Salah"])
            
            in_tanya = st.text_area("Pertanyaan")
            
            # Logic Dinamis
            final_opsi = []
            final_kunci = None
            
            st.markdown("---")
            st.write("**Masukkan Pilihan Jawaban & Kunci:**")
            
            if in_tipe == "Pilihan Ganda (1 Jawaban)":
                o1 = st.text_input("Opsi A")
                o2 = st.text_input("Opsi B")
                o3 = st.text_input("Opsi C")
                o4 = st.text_input("Opsi D")
                kunci_pilih = st.radio("Mana Jawaban Benar?", ["A", "B", "C", "D"], horizontal=True)
                final_opsi = [o1, o2, o3, o4]
                mapping = {"A":0, "B":1, "C":2, "D":3}
                if o1: final_kunci = final_opsi[mapping[kunci_pilih]]
                real_tipe = 'single'

            elif in_tipe == "Pilihan Ganda Kompleks (>1 Jawaban)":
                o1 = st.text_input("Pilihan 1")
                o2 = st.text_input("Pilihan 2")
                o3 = st.text_input("Pilihan 3")
                o4 = st.text_input("Pilihan 4")
                st.write("Centang SEMUA yang benar:")
                c1 = st.checkbox("Pilihan 1 Benar?")
                c2 = st.checkbox("Pilihan 2 Benar?")
                c3 = st.checkbox("Pilihan 3 Benar?")
                c4 = st.checkbox("Pilihan 4 Benar?")
                final_opsi = [o1, o2, o3, o4]
                final_kunci = []
                if c1: final_kunci.append(o1)
                if c2: final_kunci.append(o2)
                if c3: final_kunci.append(o3)
                if c4: final_kunci.append(o4)
                real_tipe = 'complex'

            elif in_tipe == "Benar/Salah":
                s1 = st.text_input("Pernyataan 1")
                k1 = st.radio("Kunci Pernyataan 1", ["Benar", "Salah"], horizontal=True, key="k1")
                s2 = st.text_input("Pernyataan 2")
                k2 = st.radio("Kunci Pernyataan 2", ["Benar", "Salah"], horizontal=True, key="k2")
                final_opsi = [s1, s2]
                final_kunci = {s1: k1, s2: k2}
                real_tipe = 'category'

            if st.form_submit_button("Simpan Soal"):
                if not in_tanya: st.error("Pertanyaan wajib diisi!")
                else:
                    data_soal = {"mapel": in_mapel, "topik": in_topik, "tipe": real_tipe, "pertanyaan": in_tanya, "opsi": json.dumps(final_opsi), "kunci_jawaban": json.dumps(final_kunci)}
                    db.collection('questions').add(data_soal)
                    st.success("Soal berhasil disimpan!")

    # 3. UPLOAD CSV PINTAR
    with tab3:
        st.write("Upload massal dengan Template Mudah")
        st.info("Tips: File boleh pakai pemisah koma (,) atau titik koma (;). Sistem akan otomatis mendeteksi.")
        up = st.file_uploader("File CSV", type=['csv'])
        if up and st.button("Proses Upload"):
            try:
                try:
                    df = pd.read_csv(up)
                    if len(df.columns) < 2:
                        up.seek(0)
                        df = pd.read_csv(up, sep=';')
                except:
                    up.seek(0)
                    df = pd.read_csv(up, sep=';')

                prog = st.progress(0)
                count = 0
                
                for i, r in df.iterrows():
                    if 'pilihan_a' in df.columns:
                        try:
                            raw_tipe = r.get('tipe', 'PG')
                            real_tipe = 'single'
                            if 'Check' in str(raw_tipe): real_tipe = 'complex'
                            if 'Benar' in str(raw_tipe): real_tipe = 'category'
                            
                            opsi_list = [str(r['pilihan_a']), str(r['pilihan_b']), str(r['pilihan_c']), str(r['pilihan_d'])]
                            opsi_list = [x for x in opsi_list if x != 'nan' and x != '']
                            
                            raw_kunci = str(r['jawaban_benar'])
                            final_kunci = raw_kunci
                            
                            if real_tipe == 'complex':
                                final_kunci = [x.strip() for x in raw_kunci.split(',')]
                            elif real_tipe == 'category':
                                kunci_split = [x.strip() for x in raw_kunci.split(',')]
                                final_kunci = {}
                                if len(opsi_list) >= 1 and len(kunci_split) >= 1: final_kunci[opsi_list[0]] = kunci_split[0]
                                if len(opsi_list) >= 2 and len(kunci_split) >= 2: final_kunci[opsi_list[1]] = kunci_split[1]

                            doc_data = {
                                "mapel": r['mapel'], "topik": r['topik'], "tipe": real_tipe,
                                "pertanyaan": r['pertanyaan'],
                                "opsi": json.dumps(opsi_list),
                                "kunci_jawaban": json.dumps(final_kunci)
                            }
                            db.collection('questions').add(doc_data)
                            count += 1
                        except Exception as e:
                            st.error(f"Gagal di baris {i+1}: {e}")

                    elif 'opsi' in df.columns:
                        db.collection('questions').add(r.to_dict())
                        count += 1
                    
                    prog.progress((i+1)/len(df))
                st.success(f"Selesai! {count} soal berhasil masuk.")
            except Exception as e:
                st.error(f"File bermasalah: {e}")

    # 4. SISWA
    with tab4:
        with st.form("tambah_siswa"):
            u = st.text_input("Username"); p = st.text_input("Password"); n = st.text_input("Nama")
            if st.form_submit_button("Simpan"):
                db.collection('users').document(u).set({'username':u, 'password':p, 'nama_lengkap':n})
                st.success("Tersimpan.")

# --- DASHBOARD SISWA ---
def student_page():
    st.sidebar.write(f"👤 {st.session_state['nama']}")
    st.sidebar.button("Keluar", on_click=lambda: st.session_state.clear())
    
    if 'exam_running' not in st.session_state: st.session_state['exam_running'] = False
    if 'exam_done' not in st.session_state: st.session_state['exam_done'] = False

    if st.session_state['exam_done']:
        show_result_analysis()
    elif st.session_state['exam_running']:
        exam_interface()
    else:
        st.header("Pilih Ujian")
        c1, c2 = st.columns(2)
        if c1.button("📐 Matematika"): start_exam("Matematika")
        if c2.button("📖 Bahasa Indonesia"): start_exam("Bahasa Indonesia")

def start_exam(mapel):
    q = load_questions(mapel)
    if q.empty: st.error("Soal belum ada."); return
    st.session_state.update({'exam_running':True, 'exam_done':False, 'mapel':mapel, 'q_data':q, 'start':time.time(), 'ans':{}})
    st.rerun()

def exam_interface():
    rem = (75*60) - (time.time() - st.session_state['start'])
    if rem <= 0: submit_exam(); return
    m, s = divmod(int(rem), 60)
    st.sidebar.markdown(f"<div class='timer-box'>{m:02d}:{s:02d}</div>", unsafe_allow_html=True)
    if st.sidebar.button("Kumpulkan Jawaban"): submit_exam()

    st.title(f"Soal {st.session_state['mapel']}")
    for idx, row in st.session_state['q_data'].iterrows():
        st.subheader(f"No. {idx+1}")
        st.write(row['pertanyaan'])
        
        opsi = json.loads(row['opsi'])
        key = f"q_{row['id']}"
        
        if row['tipe'] == 'single':
            st.radio("Pilih:", opsi, key=key)
        elif row['tipe'] == 'complex':
            st.multiselect("Pilih (Bisa lebih dari 1):", opsi, key=key)
        elif row['tipe'] == 'category':
            for o in opsi: st.radio(o, ["Benar", "Salah"], key=f"{key}_{o}", horizontal=True)
        
        if key in st.session_state: st.session_state['ans'][row['id']] = st.session_state[key]
        st.divider()

def submit_exam():
    score = 0; detail = []
    for idx, row in st.session_state['q_data'].iterrows():
        ans = st.session_state['ans'].get(row['id'])
        try: kunci = json.loads(row['kunci_jawaban'])
        except: kunci = row['kunci_jawaban'] 
        
        correct = False
        if row['tipe'] == 'single' and ans == kunci: correct = True
        elif row['tipe'] == 'complex' and ans and set(ans) == set(kunci): correct = True
        elif row['tipe'] == 'category' and ans == kunci: correct = True
        
        if correct: score += 1
        detail.append({'no': idx+1, 'tanya': row['pertanyaan'], 'jawab': ans, 'kunci': kunci, 'status': correct})
    
    final = (score / len(st.session_state['q_data'])) * 100
    
    data = {'username':st.session_state['username'], 'nama':st.session_state['nama'], 
            'mapel':st.session_state['mapel'], 'skor':final, 
            'tanggal':datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 'detail':json.dumps(detail, default=str)}
    db.collection('results').add(data)
    
    st.session_state.update({'exam_running':False, 'exam_done':True, 'final_score':final, 'review_data':detail})
    st.rerun()

def show_result_analysis():
    st.balloons()
    st.title(f"🎉 Hasil Ujian: {st.session_state['final_score']:.1f}")
    if st.button("Kembali ke Menu Utama"):
        st.session_state['exam_done'] = False
        st.rerun()
    st.subheader("Pembahasan Jawaban Kamu")
    for item in st.session_state['review_data']:
        with st.expander(f"No. {item['no']} - {'✅ Benar' if item['status'] else '❌ Salah'}"):
            st.write(f"**Pertanyaan:** {item['tanya']}")
            st.write(f"**Jawaban Kamu:** {item['jawab']}")
            st.write(f"**Kunci Jawaban:** {item['kunci']}")
            if not item['status']: st.markdown(":red[**Jawaban kamu masih kurang tepat.**]")
            else: st.markdown(":green[**Hebat! Jawaban kamu tepat.**]")

# --- MAIN ---
if not st.session_state['logged_in']: login_page()
else:
    if st.session_state['role'] == 'admin': admin_page()
    else: student_page()
