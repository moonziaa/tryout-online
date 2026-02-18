import streamlit as st
import pandas as pd
import time
import json
import base64
import io
import random
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(
    page_title="LATIHAN TRY OUT TKA SD", 
    page_icon="🎓", 
    layout="wide", 
    initial_sidebar_state="collapsed"
)

# Inisialisasi Font Size Default
if 'font_size' not in st.session_state: st.session_state['font_size'] = 18

# --- 2. CSS CUSTOM (UI/UX MODERN) ---
st.markdown(f"""
<style>
    /* VARIASI WARNA */
    :root {{
        --primary: #4F46E5;
        --secondary: #ec4899;
        --bg-light: #f3f4f6;
        --card-light: #ffffff;
        --text-light: #1f2937;
    }}

    /* HILANGKAN ELEMENT BAWAAN STREAMLIT */
    [data-testid="stHeader"] {{ display: none; }}
    footer {{ visibility: hidden; }}
    .stDeployButton {{ display: none; }}
    
    /* HEADER CUSTOM */
    .header-bar {{
        background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%);
        padding: 1.5rem 2rem;
        border-radius: 0 0 25px 25px;
        color: white;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        margin-bottom: 2rem;
        display: flex; justify-content: space-between; align-items: center;
    }}
    
    /* KOTAK SOAL */
    .soal-card {{
        background-color: var(--card-light);
        padding: 40px;
        border-radius: 20px;
        border: 1px solid #e5e7eb;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05);
        font-size: {st.session_state['font_size']}px;
        line-height: 1.8;
        margin-bottom: 20px;
        min-height: 400px;
    }}
    
    /* GRID NOMOR SOAL */
    .grid-box {{
        display: grid;
        grid-template-columns: repeat(5, 1fr);
        gap: 10px;
        padding: 20px;
        background: white;
        border-radius: 15px;
        border: 1px solid #e5e7eb;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }}
    
    /* Tombol Navigasi Bawah (Prev/Next) */
    .nav-container {{
        display: flex; 
        justify-content: space-between; 
        gap: 15px; 
        margin-top: 30px;
    }}
    
    /* KARTU MAPEL (Dashboard) */
    .card-dashboard {{
        padding: 30px;
        border-radius: 20px;
        text-align: center;
        color: white;
        transition: transform 0.2s;
        box-shadow: 0 10px 20px rgba(0,0,0,0.1);
        margin-bottom: 20px;
    }}
    .card-mtk {{ background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); }}
    .card-indo {{ background: linear-gradient(135deg, #ec4899 0%, #db2777 100%); }}
    .card-dashboard:hover {{ transform: translateY(-5px); }}

    /* TIMER */
    .timer-float {{
        position: fixed;
        bottom: 20px;
        right: 20px;
        background: #1f2937;
        color: white;
        padding: 10px 20px;
        border-radius: 30px;
        font-weight: bold;
        box-shadow: 0 5px 15px rgba(0,0,0,0.2);
        z-index: 999;
    }}
    
</style>
""", unsafe_allow_html=True)

# --- 3. KONEKSI DATABASE ---
@st.cache_resource
def get_db():
    try:
        if not firebase_admin._apps:
            key_dict = json.loads(json.dumps(dict(st.secrets["firebase"])))
            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)
        return firestore.client()
    except: return None

db = get_db()
if not db: st.error("Koneksi Database Gagal. Cek Secrets!"); st.stop()

# --- 4. LOGIC ---
def auto_login():
    """Anti-Logout saat refresh menggunakan Query Params"""
    try:
        qp = st.query_params
        token = qp.get("token", None)
        if token and not st.session_state.get('logged_in'):
            if token == 'admin':
                st.session_state.update({'logged_in':True, 'role':'admin', 'nama':'Guru Admin', 'username':'admin'})
            else:
                doc = db.collection('users').document(token).get()
                if doc.exists:
                    d = doc.to_dict()
                    st.session_state.update({'logged_in':True, 'role':'siswa', 'nama':d['nama_lengkap'], 'username':d['username']})
    except: pass

auto_login()

def process_image(uploaded_file):
    if uploaded_file:
        bytes_data = uploaded_file.getvalue()
        base64_str = base64.b64encode(bytes_data).decode()
        return f"data:image/png;base64,{base64_str}"
    return None

def init_exam(mapel, paket):
    session_id = f"{st.session_state['username']}_{mapel}_{paket}"
    doc_ref = db.collection('exam_sessions').document(session_id)
    doc = doc_ref.get()
    
    if doc.exists:
        data = doc.to_dict()
        if data.get('status') == 'completed':
            st.toast("Kamu sudah menyelesaikan ujian ini. Lihat nilai di menu.", icon="ℹ️")
            return False
        st.session_state.update({
            'exam_data': data, 'q_order': json.loads(data['q_order']),
            'answers': json.loads(data['answers']), 'ragu': json.loads(data.get('ragu', '[]')),
            'curr_idx': 0, 'exam_mode': True
        })
    else:
        q_ref = db.collection('questions').where('mapel', '==', mapel).where('paket', '==', paket).stream()
        q_list = [{'id': q.id, **q.to_dict()} for q in q_ref]
        
        if not q_list: st.error("Soal belum tersedia."); return False
        
        random.shuffle(q_list)
        q_order = [q['id'] for q in q_list]
        start_ts = datetime.now().timestamp()
        
        new_data = {
            'username': st.session_state['username'], 'mapel': mapel, 'paket': paket,
            'start_time': start_ts, 'end_time': start_ts + (75*60),
            'q_order': json.dumps(q_order), 'answers': "{}", 'ragu': "[]",
            'status': 'ongoing', 'score': 0
        }
        doc_ref.set(new_data)
        st.session_state.update({
            'exam_data': new_data, 'q_order': q_order, 'answers': {}, 'ragu': [], 'curr_idx': 0, 'exam_mode': True
        })
    return True

def save_realtime():
    sid = f"{st.session_state['username']}_{st.session_state['exam_data']['mapel']}_{st.session_state['exam_data']['paket']}"
    db.collection('exam_sessions').document(sid).update({
        'answers': json.dumps(st.session_state['answers']),
        'ragu': json.dumps(st.session_state['ragu'])
    })

def calculate_score():
    q_ids = st.session_state['q_order']
    ans = st.session_state['answers']
    score = 0; details = []
    
    for qid in q_ids:
        q_doc = db.collection('questions').document(qid).get()
        if not q_doc.exists: continue
        q = q_doc.to_dict()
        user_ans = ans.get(qid)
        try: key = json.loads(q['kunci_jawaban'])
        except: key = q['kunci_jawaban']
        
        correct = False
        if q['tipe'] == 'single' and user_ans == key: correct = True
        elif q['tipe'] == 'complex' and user_ans and set(user_ans) == set(key): correct = True
        elif q['tipe'] == 'category' and user_ans == key: correct = True
        
        if correct: score += 1
        details.append({'tanya': q['pertanyaan'], 'jawab': user_ans, 'kunci': key, 'benar': correct})
        
    final = (score / len(q_ids)) * 100
    sid = f"{st.session_state['username']}_{st.session_state['exam_data']['mapel']}_{st.session_state['exam_data']['paket']}"
    db.collection('exam_sessions').document(sid).update({'status': 'completed', 'score': final})
    db.collection('results').add({
        'username': st.session_state['username'], 'nama': st.session_state['nama'],
        'mapel': st.session_state['exam_data']['mapel'], 'paket': st.session_state['exam_data']['paket'],
        'skor': final, 'tanggal': datetime.now().strftime("%Y-%m-%d %H:%M"),
        'details': json.dumps(details, default=str)
    })
    return final, details

# --- 5. PAGE FUNCTIONS ---

def login_page():
    st.markdown("<br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("<h1 style='text-align:center; color:#4F46E5;'>🎓 CAT TKA SD</h1>", unsafe_allow_html=True)
        st.markdown("<div style='background:white; padding:30px; border-radius:20px; box-shadow:0 10px 30px rgba(0,0,0,0.1);'>", unsafe_allow_html=True)
        
        tab_login, tab_register = st.tabs(["🔑 Masuk", "📝 Daftar Akun"])
        
        with tab_login:
            with st.form("login_form"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                if st.form_submit_button("Masuk", use_container_width=True, type="primary"):
                    if u=="admin" and p=="admin123":
                        st.session_state.update({'logged_in':True, 'role':'admin', 'nama':'Admin', 'username':'admin'})
                        st.query_params["token"] = "admin"
                        st.rerun()
                    else:
                        users = db.collection('users').where('username','==',u).where('password','==',p).stream()
                        found = False
                        for user in users:
                            d = user.to_dict()
                            st.session_state.update({'logged_in':True, 'role':'siswa', 'nama':d['nama_lengkap'], 'username':d['username']})
                            st.query_params["token"] = d['username']
                            found = True; st.rerun()
                        if not found: st.error("Username/Password salah")
        
        with tab_register:
            with st.form("reg_form"):
                nu = st.text_input("Buat Username (Tanpa Spasi)")
                nn = st.text_input("Nama Lengkap")
                np = st.text_input("Buat Password", type="password")
                if st.form_submit_button("Daftar Sekarang", use_container_width=True):
                    if nu and nn and np:
                        chk = db.collection('users').document(nu).get()
                        if chk.exists: st.error("Username sudah dipakai, cari yang lain.")
                        else:
                            db.collection('users').document(nu).set({'username':nu, 'password':np, 'nama_lengkap':nn, 'role':'siswa'})
                            st.success("Berhasil! Silakan klik tab Masuk.")
                    else: st.warning("Isi semua kolom ya.")
        st.markdown("</div>", unsafe_allow_html=True)

def admin_dashboard():
    # Header Admin
    st.markdown(f"""
    <div class='header-bar'>
        <div>
            <h2 style='margin:0'>Dashboard Guru</h2>
            <p style='margin:0; opacity:0.8'>Kelola Soal & Siswa</p>
        </div>
        <a href='/?logout=true' style='background:rgba(255,255,255,0.2); padding:8px 15px; border-radius:8px; color:white; text-decoration:none;'>Keluar</a>
    </div>
    """, unsafe_allow_html=True)
    
    if st.query_params.get("logout"): st.query_params.clear(); st.session_state.clear(); st.rerun()
    
    t1, t2, t3, t4 = st.tabs(["📝 Input Soal", "📂 Upload CSV", "🛠️ Edit Bank Soal", "👥 Data Siswa"])
    
    # INPUT SOAL DINAMIS
    with t1:
        st.subheader("Input Soal Baru")
        # PENTING: Selectbox DI LUAR FORM agar interaktif
        c1, c2 = st.columns(2)
        v_mapel = c1.selectbox("Mapel", ["Matematika", "Bahasa Indonesia"])
        v_paket = c2.text_input("Nama Paket", "Paket 1")
        v_tipe = st.selectbox("Tipe Soal", ["Pilihan Ganda (PG)", "PG Kompleks", "Benar/Salah"])
        
        with st.form("frm_soal"):
            v_tanya = st.text_area("Pertanyaan")
            v_img = st.file_uploader("Gambar (Opsional)", type=['png','jpg','jpeg'])
            
            opsi = []; kunci = None
            st.markdown("---")
            
            # Logic Tampilan Berdasarkan Tipe
            if v_tipe == "Pilihan Ganda (PG)":
                cols = st.columns(4)
                opsi = [cols[i].text_input(f"Opsi {chr(65+i)}") for i in range(4)]
                ans = st.radio("Kunci Jawaban", ["A","B","C","D"], horizontal=True)
                if opsi[0]: kunci = opsi[ord(ans)-65]
                rt = 'single'
                
            elif v_tipe == "PG Kompleks":
                st.info("Centang semua jawaban benar")
                cols = st.columns(2); k_list = []
                for i in range(4):
                    val = cols[i%2].text_input(f"Pilihan {i+1}")
                    if val: opsi.append(val)
                    if cols[i%2].checkbox(f"Benar?", key=f"k_{i}"): k_list.append(val)
                kunci = k_list; rt = 'complex'
                
            elif v_tipe == "Benar/Salah":
                kunci = {}
                for i in range(3):
                    c_a, c_b = st.columns([3,1])
                    p = c_a.text_input(f"Pernyataan {i+1}")
                    k = c_b.radio(f"Kunci", ["Benar","Salah"], horizontal=True, key=f"bs_{i}", label_visibility="collapsed")
                    if p: opsi.append(p); kunci[p] = k
                rt = 'category'
            
            if st.form_submit_button("Simpan Soal"):
                im_data = process_image(v_img)
                db.collection('questions').add({
                    'mapel':v_mapel, 'paket':v_paket, 'tipe':rt, 'pertanyaan':v_tanya, 
                    'gambar':im_data, 'opsi':json.dumps(opsi), 'kunci_jawaban':json.dumps(kunci)
                })
                st.success("Soal tersimpan ke database!")

    # UPLOAD CSV
    with t2:
        st.info("Format: Pipa (|) sebagai pemisah. Copy dari Chatbot.")
        txt = st.text_area("Paste Teks CSV disini", height=200)
        if st.button("Proses Upload"):
            try:
                df = pd.read_csv(io.StringIO(txt), sep='|')
                cnt = 0
                for _, r in df.iterrows():
                    o = [str(r[c]) for c in ['pilihan_a','pilihan_b','pilihan_c','pilihan_d'] if pd.notna(r[c])]
                    rt='single'; rk=str(r['jawaban_benar']); fk=rk
                    if 'Check' in str(r['tipe']): rt='complex'; fk=[x.strip() for x in rk.split(',')]
                    elif 'Benar' in str(r['tipe']): 
                        rt='category'; ks=[x.strip() for x in rk.split(',')]
                        fk={o[i]:ks[i] for i in range(len(ks)) if i<len(o)}
                    db.collection('questions').add({'mapel':r['mapel'], 'paket':'Paket 1', 'tipe':rt, 'pertanyaan':r['pertanyaan'], 'gambar':None, 'opsi':json.dumps(o), 'kunci_jawaban':json.dumps(fk)})
                    cnt+=1
                st.success(f"Masuk {cnt} soal!")
            except Exception as e: st.error(f"Error: {e}")

    # EDIT SOAL
    with t3:
        f_m = st.selectbox("Mapel", ["Matematika","Bahasa Indonesia"], key="fm")
        f_p = st.text_input("Paket", "Paket 1", key="fp")
        qs = list(db.collection('questions').where('mapel','==',f_m).where('paket','==',f_p).stream())
        
        if qs:
            q_data = [{'id':q.id, **q.to_dict()} for q in qs]
            sel = st.selectbox("Pilih Soal", range(len(q_data)), format_func=lambda x: q_data[x]['pertanyaan'][:80])
            q = q_data[sel]
            
            with st.form("edit_f"):
                nt = st.text_area("Edit Tanya", q['pertanyaan'])
                if q.get('gambar'): st.image(q['gambar'], width=200)
                ni = st.file_uploader("Ganti Gambar")
                
                # Edit Opsi JSON mentah (paling fleksibel)
                no = st.text_area("Opsi (JSON)", q['opsi'])
                nk = st.text_area("Kunci (JSON)", q['kunci_jawaban'])
                
                c_up, c_del = st.columns(2)
                if c_up.form_submit_button("Update"):
                    ud = {'pertanyaan':nt, 'opsi':no, 'kunci_jawaban':nk}
                    if ni: ud['gambar'] = process_image(ni)
                    db.collection('questions').document(q['id']).update(ud)
                    st.success("Updated!"); time.sleep(1); st.rerun()
                if c_del.form_submit_button("Hapus", type="primary"):
                    db.collection('questions').document(q['id']).delete(); st.rerun()
        else: st.warning("Kosong.")

    # SISWA
    with t4:
        users = list(db.collection('users').where('role','!=','admin').stream())
        if users:
            dt = pd.DataFrame([u.to_dict() for u in users])
            st.dataframe(dt[['username','nama_lengkap']], use_container_width=True)
            st.caption("Total: " + str(len(users)) + " siswa. Password disembunyikan.")

def student_dashboard():
    # Header Cantik
    st.markdown(f"""
    <div class='header-bar'>
        <div>
            <h2 style='margin:0'>Halo, {st.session_state['nama']}! 👋</h2>
            <p style='margin:0; opacity:0.9'>Semangat latihan hari ini!</p>
        </div>
        <a href='/?logout=true' style='background:rgba(255,255,255,0.3); padding:8px 15px; border-radius:8px; color:white; text-decoration:none; font-weight:bold;'>Keluar</a>
    </div>
    """, unsafe_allow_html=True)
    
    if st.query_params.get("logout"): st.query_params.clear(); st.session_state.clear(); st.rerun()
    
    st.subheader("Pilih Mata Pelajaran")
    
    # CARD LAYOUT
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='card-dashboard card-mtk'><h3>📐 Matematika</h3><p>Paket Soal Lengkap</p></div>", unsafe_allow_html=True)
        if st.button("Mulai Paket 1", key="btn_mtk", use_container_width=True, type="primary"):
            if init_exam("Matematika", "Paket 1"): st.rerun()
            
    with c2:
        st.markdown("<div class='card-dashboard card-indo'><h3>📖 B. Indonesia</h3><p>Paket Soal Literasi</p></div>", unsafe_allow_html=True)
        st.button("Belum Tersedia", disabled=True, use_container_width=True)

def exam_interface():
    data = st.session_state['exam_data']; order = st.session_state['q_order']; idx = st.session_state['curr_idx']
    
    # Timer Float
    rem = data['end_time'] - datetime.now().timestamp()
    if rem <= 0: finish_exam()
    st.markdown(f"<div class='timer-float'>⏱️ {int(rem//60)}:{int(rem%60):02d}</div>", unsafe_allow_html=True)
    
    # Header Simple
    c1, c2 = st.columns([3, 1])
    with c1: st.subheader(f"{data['mapel']}")
    with c2: 
        # Font Resizer
        f = st.columns(3)
        if f[0].button("A-"): st.session_state['font_size']=14; st.rerun()
        if f[1].button("A"): st.session_state['font_size']=18; st.rerun()
        if f[2].button("A+"): st.session_state['font_size']=24; st.rerun()
    
    # --- LAYOUT UTAMA (GRID DI KANAN KALAU LAPTOP, DI BAWAH KALAU HP) ---
    # Streamlit otomatis menumpuk kolom 2 ke bawah kolom 1 di layar kecil (HP)
    col_soal, col_grid = st.columns([3, 1])
    
    # --- KOLOM SOAL ---
    with col_soal:
        qid = order[idx]
        q_doc = db.collection('questions').document(qid).get()
        
        if q_doc.exists:
            q = q_doc.to_dict()
            st.markdown(f"<div class='soal-card'><strong>Soal No. {idx+1}</strong><br><br>{q['pertanyaan']}</div>", unsafe_allow_html=True)
            if q.get('gambar'): st.image(q['gambar'])
            
            # Input Jawaban
            opsi = json.loads(q['opsi']); ans = st.session_state['answers'].get(qid)
            
            if q['tipe'] == 'single':
                sel = st.radio("Pilih:", opsi, key=qid, index=opsi.index(ans) if ans in opsi else None)
                if sel: st.session_state['answers'][qid] = sel
            elif q['tipe'] == 'complex':
                st.write("**Pilih Lebih dari Satu:**")
                sel = ans if isinstance(ans, list) else []; new_sel = []
                for o in opsi:
                    if st.checkbox(o, o in sel, key=f"{qid}_{o}"): new_sel.append(o)
                st.session_state['answers'][qid] = new_sel
            elif q['tipe'] == 'category':
                st.write("**Tentukan Benar/Salah:**")
                sel = ans if isinstance(ans, dict) else {}; new_sel = {}
                for o in opsi:
                    ca, cb = st.columns([3,1]); ca.write(o)
                    v = cb.radio(f"bn_{o}", ["Benar","Salah"], key=f"{qid}_{o}", horizontal=True, label_visibility="collapsed", index=0 if sel.get(o)=="Benar" else 1 if sel.get(o)=="Salah" else None)
                    if v: new_sel[o] = v
                st.session_state['answers'][qid] = new_sel

        # TOMBOL NAVIGASI BAWAH (PREV - NEXT - FINISH)
        st.markdown("<br>", unsafe_allow_html=True)
        c_prev, c_ragu, c_next = st.columns([1, 1, 1])
        
        # Logic Tombol
        if idx > 0:
            if c_prev.button("⬅️ Sebelumnya", use_container_width=True):
                st.session_state['curr_idx'] -= 1; save_realtime(); st.rerun()
        
        is_r = qid in st.session_state['ragu']
        if c_ragu.button(f"{'🟨 Batal Ragu' if is_r else '🟨 Ragu'}", use_container_width=True):
            if is_r: st.session_state['ragu'].remove(qid)
            else: st.session_state['ragu'].append(qid)
            save_realtime(); st.rerun()
            
        if idx < len(order)-1:
            if c_next.button("Selanjutnya ➡️", use_container_width=True, type="primary"):
                st.session_state['curr_idx'] += 1; save_realtime(); st.rerun()
        else:
            if c_next.button("✅ Selesai", use_container_width=True, type="primary"):
                finish_exam()

    # --- KOLOM GRID (OTOMATIS PINDAH KE BAWAH DI HP) ---
    with col_grid:
        st.markdown("**Nomor Soal**")
        
        # Container grid manual biar rapi
        cols = st.columns(5)
        for i, q_id in enumerate(order):
            label = str(i+1)
            # Visual Marker di label karena keterbatasan styling button native
            if i == idx: label = f"🔵 {i+1}"
            elif q_id in st.session_state['ragu']: label = f"🟡 {i+1}"
            elif q_id in st.session_state['answers'] and st.session_state['answers'][q_id]: label = f"✅ {i+1}"
            
            if cols[i%5].button(label, key=f"nav_{i}", use_container_width=True):
                st.session_state['curr_idx'] = i; save_realtime(); st.rerun()
                
        st.caption("🔵: Aktif | ✅: Dijawab | 🟡: Ragu")

def finish_exam():
    save_realtime()
    sc, det = calculate_score()
    st.session_state.update({'exam_mode':False, 'result_mode':True, 'last_score':sc, 'last_det':det})
    st.rerun()

def result_interface():
    st.balloons()
    st.markdown(f"""
    <div style='text-align:center; padding:40px; background:white; border-radius:20px; box-shadow:0 10px 25px rgba(0,0,0,0.1); margin-top:50px;'>
        <h1 style='color:#4F46E5; font-size:3rem; margin:0;'>{st.session_state['last_score']:.1f}</h1>
        <p style='font-size:1.2rem; color:gray;'>Nilai Akhir Kamu</p>
        <hr style='margin:20px 0;'>
        <p>Tetap semangat belajar dan tingkatkan terus prestasimu!</p>
    </div>
    <br>
    """, unsafe_allow_html=True)
    
    if st.button("Kembali ke Beranda", use_container_width=True):
        st.session_state['result_mode']=False; st.rerun()
        
    with st.expander("Lihat Pembahasan Jawaban"):
        for d in st.session_state['last_det']:
            color = "#dcfce7" if d['benar'] else "#fee2e2"
            icon = "✅" if d['benar'] else "❌"
            st.markdown(f"""
            <div style='background:{color}; padding:15px; border-radius:10px; margin-bottom:10px; color:black; border:1px solid rgba(0,0,0,0.05);'>
                <strong>{icon} {d['tanya']}</strong><br>
                <div style='margin-top:5px; font-size:0.9em;'>
                    Jawabanmu: <b>{d['jawab']}</b> <br>
                    Kunci: <b>{d['kunci']}</b>
                </div>
            </div>
            """, unsafe_allow_html=True)

# Main Loop
if not st.session_state.get('logged_in'): login_page()
else:
    if st.session_state['role'] == 'admin': admin_dashboard()
    else:
        if st.session_state.get('exam_mode'): exam_interface()
        elif st.session_state.get('result_mode'): result_interface()
        else: student_dashboard()
