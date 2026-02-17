import streamlit as st
import pandas as pd
import time
import json
import random
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, firestore
import altair as alt

# --- 1. KONFIGURASI & CSS ---
st.set_page_config(page_title="CAT TKA SD", page_icon="🎓", layout="wide", initial_sidebar_state="collapsed")

# Inisialisasi Session State untuk Font Size
if 'font_size' not in st.session_state: st.session_state['font_size'] = '18px'

# CSS Custom ala PUSMENDIK/ANBK
st.markdown(f"""
<style>
    /* Reset & Base */
    [data-testid="stAppViewContainer"] {{ background-color: #f0f3f5; color: #333; }}
    [data-testid="stHeader"] {{ display: none; }} /* Sembunyikan header bawaan */
    
    /* Header Custom */
    .custom-header {{
        background: linear-gradient(90deg, #1e3a8a, #3b82f6);
        padding: 15px 20px;
        color: white;
        border-radius: 0 0 15px 15px;
        margin-bottom: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        display: flex; justify-content: space-between; align-items: center;
    }}
    
    /* Soal Container */
    .soal-container {{
        background: white;
        padding: 30px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        font-size: {st.session_state['font_size']};
        line-height: 1.6;
        min-height: 400px;
    }}
    
    /* Tombol Navigasi Bawah */
    .nav-btn {{ width: 100%; font-weight: bold; border-radius: 5px; }}
    
    /* Nomor Soal Grid */
    .grid-container {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }}
    .grid-item {{
        padding: 10px; text-align: center; border: 1px solid #ccc; border-radius: 5px;
        cursor: pointer; font-weight: bold; font-size: 14px;
    }}
    .status-done {{ background-color: #4ade80; color: white; border: 1px solid #22c55e; }} /* Hijau */
    .status-ragu {{ background-color: #facc15; color: black; border: 1px solid #eab308; }} /* Kuning */
    .status-current {{ border: 2px solid #2563eb; transform: scale(1.05); }} /* Biru Highlight */
    
    /* Tombol Ukuran Font */
    .font-btn {{ padding: 2px 8px; border: 1px solid white; color: white; border-radius: 4px; cursor: pointer; margin-left: 5px; font-size: 12px; }}
    .font-btn:hover {{ background-color: rgba(255,255,255,0.2); }}

    /* Hide Default Streamlit Elements */
    footer {{ visibility: hidden; }}
    .stDeployButton {{ display: none; }}
</style>
""", unsafe_allow_html=True)

# --- 2. KONEKSI DATABASE ---
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
    st.error("Gagal koneksi database. Pastikan Secrets sudah diatur.")
    st.stop()

# --- 3. FUNGSI LOGIC ---

def get_session_id():
    """Membuat ID unik untuk sesi ujian berdasarkan user dan paket"""
    return f"{st.session_state['username']}_{st.session_state.get('selected_mapel','')}_{st.session_state.get('selected_paket','')}"

def init_exam_session(mapel, paket):
    """Memulai sesi ujian: Ambil soal, Acak, Simpan urutan ke DB"""
    session_id = f"{st.session_state['username']}_{mapel}_{paket}"
    
    # Cek apakah sudah ada sesi berjalan di DB (Resume)
    doc_ref = db.collection('exam_sessions').document(session_id)
    doc = doc_ref.get()
    
    if doc.exists:
        data = doc.to_dict()
        if data.get('status') == 'ongoing':
            st.session_state['exam_data'] = data
            st.session_state['q_order'] = json.loads(data['q_order'])
            st.session_state['answers'] = json.loads(data['answers'])
            st.session_state['ragu'] = json.loads(data.get('ragu', '[]'))
            return True
        elif data.get('status') == 'completed':
            return False # Sudah selesai

    # Jika belum ada, buat sesi baru
    # 1. Ambil soal dari DB
    questions_ref = db.collection('questions').where('mapel', '==', mapel).where('paket', '==', paket).stream()
    q_list = []
    for q in questions_ref:
        qd = q.to_dict()
        qd['id'] = q.id
        q_list.append(qd)
    
    if not q_list:
        st.error("Soal tidak ditemukan untuk paket ini.")
        return False

    # 2. Randomize (Acak Soal)
    random.shuffle(q_list)
    q_order = [q['id'] for q in q_list] # Simpan ID saja biar ringan
    
    # 3. Simpan state awal ke DB
    start_time = datetime.now().timestamp()
    duration = 75 * 60 # 75 menit
    end_time = start_time + duration
    
    session_data = {
        'username': st.session_state['username'],
        'mapel': mapel,
        'paket': paket,
        'start_time': start_time,
        'end_time': end_time,
        'q_order': json.dumps(q_order),
        'answers': json.dumps({}),
        'ragu': json.dumps([]),
        'status': 'ongoing',
        'score': 0
    }
    doc_ref.set(session_data)
    
    st.session_state['exam_data'] = session_data
    st.session_state['q_order'] = q_order
    st.session_state['answers'] = {}
    st.session_state['ragu'] = []
    return True

def save_answer_realtime():
    """Simpan jawaban ke DB setiap pindah soal (Auto-save)"""
    session_id = get_session_id()
    db.collection('exam_sessions').document(session_id).update({
        'answers': json.dumps(st.session_state['answers']),
        'ragu': json.dumps(st.session_state['ragu'])
    })

def calculate_score_and_finish():
    """Hitung nilai, simpan ke riwayat, tutup sesi"""
    session_id = get_session_id()
    q_ids = st.session_state['q_order']
    answers = st.session_state['answers']
    
    score = 0
    total = len(q_ids)
    details = []
    
    # Ambil data soal asli (batch fetch biar cepat) - Simplifikasi: fetch one by one atau cache
    # Untuk akurasi, kita fetch ulang based on ID
    for q_id in q_ids:
        q_doc = db.collection('questions').document(q_id).get()
        q_data = q_doc.to_dict()
        
        user_ans = answers.get(q_id)
        try: real_key = json.loads(q_data['kunci_jawaban'])
        except: real_key = q_data['kunci_jawaban']
        
        # Logika Penilaian
        is_correct = False
        tipe = q_data['tipe']
        
        if tipe == 'single':
            if user_ans == real_key: is_correct = True
        elif tipe == 'complex':
            # Harus sama persis set-nya
            if user_ans and set(user_ans) == set(real_key): is_correct = True
        elif tipe == 'category':
            if user_ans == real_key: is_correct = True
            
        if is_correct: score += 1
        
        details.append({
            'q_id': q_id,
            'pertanyaan': q_data['pertanyaan'],
            'user_ans': user_ans,
            'key': real_key,
            'is_correct': is_correct,
            'tipe': tipe
        })
        
    final_score = (score / total) * 100
    
    # Update Session jadi Completed
    db.collection('exam_sessions').document(session_id).update({
        'status': 'completed',
        'score': final_score,
        'finished_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    
    # Simpan ke tabel Results (Riwayat Nilai Tertinggi logic bisa di handle di UI)
    result_data = {
        'username': st.session_state['username'],
        'nama': st.session_state['nama'],
        'mapel': st.session_state['exam_data']['mapel'],
        'paket': st.session_state['exam_data']['paket'],
        'skor': final_score,
        'tanggal': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'details': json.dumps(details, default=str)
    }
    db.collection('results').add(result_data)
    
    return final_score, details

# --- 4. HALAMAN-HALAMAN ---

def login_page():
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("<h2 style='text-align: center; color: #1e3a8a;'>🎓 Login Try Out TKA</h2>", unsafe_allow_html=True)
        with st.form("login_form"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Masuk", use_container_width=True)
            
            if submitted:
                if u == "admin" and p == "admin123":
                    st.session_state.update({'logged_in':True, 'role':'admin', 'nama':'Administrator', 'username':'admin'})
                    st.rerun()
                else:
                    users = db.collection('users').where('username', '==', u).where('password', '==', p).stream()
                    found = False
                    for user in users:
                        d = user.to_dict()
                        st.session_state.update({'logged_in':True, 'role':'siswa', 'nama':d['nama_lengkap'], 'username':d['username']})
                        found = True
                        st.rerun()
                    if not found: st.error("Username atau Password salah!")

def admin_page():
    st.markdown("""
    <div class='custom-header'>
        <h3>🛠️ Dashboard Admin</h3>
        <button style='background:none; border:1px solid white; color:white; padding:5px 10px; border-radius:5px;' 
        onclick="window.location.reload()">Log Out</button>
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("Keluar"): st.session_state.clear(); st.rerun()

    tab1, tab2, tab3 = st.tabs(["👥 Manajemen Siswa", "📝 Input Soal", "📊 Rekap Nilai"])
    
    # TAB 1: MANAJEMEN SISWA
    with tab1:
        st.subheader("Daftar Akun Siswa")
        
        # Load data siswa
        users_ref = db.collection('users').where('role', '!=', 'admin').stream()
        users_data = [{'id': u.id, **u.to_dict()} for u in users_ref]
        
        if users_data:
            df_users = pd.DataFrame(users_data)
            # Tampilkan sebagai Data Editor agar bisa diedit langsung
            edited_df = st.data_editor(df_users[['username', 'password', 'nama_lengkap']], num_rows="dynamic", key="user_editor")
            
            if st.button("Simpan Perubahan Akun"):
                # Logic sederhana: Loop dan update (kurang efisien untuk data besar, tapi oke untuk skala SD)
                # Note: Data Editor Streamlit mengembalikan dataframe baru.
                # Untuk implementasi CRUD full di data editor butuh logic diff.
                # Sederhananya, kita pakai form tambah manual dan list view saja agar aman.
                pass
                
            st.info("Untuk mengedit/menghapus, gunakan menu di bawah tabel ini (agar lebih aman).")
            
            # Tabel View
            st.dataframe(df_users[['nama_lengkap', 'username', 'password']])
            
            c_edit, c_hapus = st.columns(2)
            with c_edit:
                st.write("Edit Password/Nama")
                pilih_user = st.selectbox("Pilih Siswa", df_users['username'].tolist())
                new_pass = st.text_input("Password Baru")
                new_name = st.text_input("Nama Baru")
                if st.button("Update Akun"):
                    db.collection('users').document(pilih_user).update({'password': new_pass, 'nama_lengkap': new_name})
                    st.success("Updated!")
                    time.sleep(1); st.rerun()
            
            with c_hapus:
                st.write("Hapus Akun (Hati-hati)")
                hapus_user = st.selectbox("Hapus Siswa", df_users['username'].tolist(), key='del_user')
                if st.button("Hapus Permanen"):
                    db.collection('users').document(hapus_user).delete()
                    st.warning("Terhapus.")
                    time.sleep(1); st.rerun()

        st.divider()
        st.subheader("Tambah Siswa Baru")
        with st.form("add_student"):
            c1, c2, c3 = st.columns(3)
            nu = c1.text_input("Username")
            np = c2.text_input("Password")
            nn = c3.text_input("Nama Lengkap")
            if st.form_submit_button("Buat Akun"):
                db.collection('users').document(nu).set({
                    'username': nu, 'password': np, 'nama_lengkap': nn, 'role': 'siswa'
                })
                st.success(f"Siswa {nn} berhasil dibuat.")
                st.rerun()

    # TAB 2: INPUT SOAL (FIXED LOGIC)
    with tab2:
        st.subheader("Bank Soal")
        
        with st.form("input_soal_fix"):
            c1, c2, c3 = st.columns(3)
            in_mapel = c1.selectbox("Mapel", ["Matematika", "Bahasa Indonesia"])
            in_paket = c2.text_input("Paket Soal", value="Paket 1", help="Contoh: Paket A, Tryout 1")
            in_tipe = c3.selectbox("Tipe Soal", ["Pilihan Ganda (PG)", "PG Kompleks (Checkbox)", "Benar/Salah"])
            
            in_tanya = st.text_area("Pertanyaan Soal")
            
            final_opsi = []
            final_kunci = None
            
            st.markdown("**Opsi Jawaban & Kunci**")
            
            if in_tipe == "Pilihan Ganda (PG)":
                o1 = st.text_input("A")
                o2 = st.text_input("B")
                o3 = st.text_input("C")
                o4 = st.text_input("D")
                kunci = st.radio("Kunci Jawaban", ["A", "B", "C", "D"], horizontal=True)
                
                final_opsi = [o1, o2, o3, o4]
                map_k = {"A":0, "B":1, "C":2, "D":3}
                if o1: final_kunci = final_opsi[map_k[kunci]]
                tipe_db = 'single'
                
            elif in_tipe == "PG Kompleks (Checkbox)":
                st.info("Isi opsi jawaban, lalu centang mana saja yang benar.")
                col_opsi = st.columns(4)
                checks = st.columns(4)
                
                temp_opsi = []
                temp_kunci = []
                
                for i in range(4):
                    val = col_opsi[i].text_input(f"Opsi {i+1}")
                    is_true = checks[i].checkbox(f"Benar?", key=f"chk_{i}")
                    temp_opsi.append(val)
                    if is_true: temp_kunci.append(val)
                
                final_opsi = temp_opsi
                final_kunci = temp_kunci # List jawaban benar
                tipe_db = 'complex'
                
            elif in_tipe == "Benar/Salah":
                st.info("Masukkan pernyataan, lalu tentukan kuncinya.")
                p1 = st.text_input("Pernyataan 1")
                k1 = st.radio("Kunci 1", ["Benar", "Salah"], horizontal=True, key="k1")
                p2 = st.text_input("Pernyataan 2")
                k2 = st.radio("Kunci 2", ["Benar", "Salah"], horizontal=True, key="k2")
                
                final_opsi = [p1, p2]
                final_kunci = {p1: k1, p2: k2} # Dict
                tipe_db = 'category'
            
            if st.form_submit_button("Simpan Soal"):
                data = {
                    'mapel': in_mapel,
                    'paket': in_paket, # Support Multi Paket
                    'tipe': tipe_db,
                    'pertanyaan': in_tanya,
                    'opsi': json.dumps(final_opsi),
                    'kunci_jawaban': json.dumps(final_kunci),
                    'created_at': datetime.now().strftime("%Y-%m-%d")
                }
                db.collection('questions').add(data)
                st.success("Soal tersimpan!")

    # TAB 3: REKAP
    with tab3:
        if st.button("Refresh Data"): st.rerun()
        res_ref = db.collection('results').order_by('tanggal', direction=firestore.Query.DESCENDING).stream()
        res_data = [r.to_dict() for r in res_ref]
        
        if res_data:
            df_res = pd.DataFrame(res_data)
            st.dataframe(df_res[['tanggal', 'nama', 'mapel', 'paket', 'skor']])
            
            # Grafik
            chart = alt.Chart(df_res).mark_bar().encode(
                x='nama',
                y='skor',
                color='mapel',
                tooltip=['nama', 'skor', 'paket']
            ).interactive()
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("Belum ada data ujian.")

def student_dashboard():
    # Header Siswa
    st.markdown(f"""
    <div class='custom-header'>
        <div>
            <h3>Halo, {st.session_state['nama']}</h3>
            <p style='font-size:14px; margin:0;'>Semangat belajar!</p>
        </div>
        <div>
            <button style='background:#ef4444; border:none; color:white; padding:8px 15px; border-radius:5px; cursor:pointer;' 
            onclick="window.location.reload()">Keluar</button>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    if st.sidebar.button("Log Out"): st.session_state.clear(); st.rerun()

    # Cek State Ujian
    if 'exam_mode' in st.session_state and st.session_state['exam_mode']:
        exam_interface()
    elif 'result_mode' in st.session_state and st.session_state['result_mode']:
        result_interface()
    else:
        # MENU UTAMA (Pilih Mapel & Paket)
        st.subheader("📚 Pilih Ujian")
        
        # Ambil paket yang tersedia dari DB (Unique Paket)
        # Note: Ini agak berat query-nya kalau data besar, idealnya ada koleksi 'pakets' terpisah.
        # Kita pakai pendekatan: User pilih Mapel dulu.
        
        col1, col2 = st.columns(2)
        with col1:
            st.info("📐 Matematika")
            if st.button("Lihat Paket Matematika"):
                st.session_state['selected_mapel'] = 'Matematika'
        with col2:
            st.info("📖 Bahasa Indonesia")
            if st.button("Lihat Paket B. Indonesia"):
                st.session_state['selected_mapel'] = 'Bahasa Indonesia'
                
        if 'selected_mapel' in st.session_state:
            st.markdown(f"### Paket Soal: {st.session_state['selected_mapel']}")
            
            # Cari paket yang ada
            q_ref = db.collection('questions').where('mapel', '==', st.session_state['selected_mapel']).stream()
            pakets = set()
            for q in q_ref:
                d = q.to_dict()
                pakets.add(d.get('paket', 'Tanpa Paket'))
            
            if not pakets:
                st.warning("Belum ada soal untuk mapel ini.")
            else:
                for pkt in list(pakets):
                    with st.container():
                        c_a, c_b = st.columns([3, 1])
                        c_a.write(f"**{pkt}** (30 Soal - 75 Menit)")
                        # Cek history nilai tertinggi
                        hist_ref = db.collection('results').where('username', '==', st.session_state['username']).where('paket', '==', pkt).stream()
                        best_score = 0
                        has_attempt = False
                        for h in hist_ref:
                            has_attempt = True
                            s = h.to_dict().get('skor', 0)
                            if s > best_score: best_score = s
                        
                        if has_attempt:
                            c_a.caption(f"Nilai Tertinggi: {best_score:.1f}")
                            btn_label = "Ulangi Ujian"
                        else:
                            btn_label = "Mulai Kerjakan"
                            
                        if c_b.button(btn_label, key=f"start_{pkt}"):
                            success = init_exam_session(st.session_state['selected_mapel'], pkt)
                            if success:
                                st.session_state['exam_mode'] = True
                                st.session_state['current_idx'] = 0
                                st.rerun()

def exam_interface():
    data = st.session_state['exam_data']
    q_order = st.session_state['q_order']
    curr_idx = st.session_state.get('current_idx', 0)
    total_q = len(q_order)
    
    # 1. HEADER UJIAN (Sticky)
    # Hitung sisa waktu server-side
    now_ts = datetime.now().timestamp()
    r
