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
import altair as alt

# --- 1. KONFIGURASI HALAMAN (WAJIB PALING ATAS) ---
st.set_page_config(
    page_title="CAT TKA SD", 
    page_icon="🎓", 
    layout="wide", 
    initial_sidebar_state="collapsed"
)

# Init Font Size
if 'font_size' not in st.session_state: st.session_state['font_size'] = 18

# --- 2. CSS CUSTOM (TAMPILAN PREMIUM & RESPONSIF) ---
st.markdown(f"""
<style>
    /* VARIASI WARNA */
    :root {{
        --primary: #4F46E5;
        --secondary: #EC4899;
        --bg-light: #F3F4F6;
        --card-bg: #ffffff;
        --text-dark: #1F2937;
    }}

    /* HILANGKAN ELEMENT BAWAAN */
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
        background-color: var(--card-bg);
        padding: 30px;
        border-radius: 20px;
        border: 1px solid #e5e7eb;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
        font-size: {st.session_state['font_size']}px;
        line-height: 1.8;
        margin-bottom: 20px;
        min-height: 400px;
    }}
    
    /* TOMBOL GRID NOMOR */
    .grid-btn {{
        width: 100%; aspect-ratio: 1; 
        display: flex; align-items: center; justify-content: center;
        border-radius: 8px; font-weight: bold; cursor: pointer;
        font-size: 14px; margin-bottom: 5px;
        border: 1px solid #e5e7eb;
        background: white; color: #333;
    }}
    
    /* NAVIGASI BAWAH */
    .nav-container {{
        display: flex; justify-content: space-between; margin-top: 20px;
    }}
    
    /* DASHBOARD CARDS */
    .card-dashboard {{
        padding: 25px; border-radius: 15px; text-align: center; color: white;
        box-shadow: 0 10px 20px rgba(0,0,0,0.1); margin-bottom: 15px;
        transition: transform 0.2s;
    }}
    .card-dashboard:hover {{ transform: translateY(-3px); }}
    .card-mtk {{ background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); }}
    .card-indo {{ background: linear-gradient(135deg, #ec4899 0%, #db2777 100%); }}
    
    /* STATISTIK CARD */
    .stat-box {{
        background: white; padding: 20px; border-radius: 12px;
        border: 1px solid #e5e7eb; text-align: center;
    }}
    .stat-val {{ font-size: 24px; font-weight: bold; color: #4F46E5; }}
    .stat-lbl {{ font-size: 12px; color: gray; }}

    /* TIMER */
    .timer-float {{
        position: fixed; bottom: 20px; right: 20px;
        background: #1f2937; color: white; padding: 10px 20px;
        border-radius: 30px; font-weight: bold; z-index: 999;
        box-shadow: 0 5px 15px rgba(0,0,0,0.3);
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
    
    start_new = True
    if doc.exists:
        data = doc.to_dict()
        # Jika status ongoing, lanjutkan
        if data.get('status') == 'ongoing':
            now = datetime.now().timestamp()
            if now < data.get('end_time', 0):
                st.session_state.update({
                    'exam_data': data, 'q_order': json.loads(data['q_order']),
                    'answers': json.loads(data['answers']), 'ragu': json.loads(data.get('ragu', '[]')),
                    'curr_idx': 0, 'exam_mode': True
                })
                start_new = False
                st.toast("Melanjutkan sesi ujian...", icon="🔄")
    
    if start_new:
        # Fetch soal
        q_ref = db.collection('questions').where('mapel', '==', mapel).where('paket', '==', paket).stream()
        q_list = [{'id': q.id, **q.to_dict()} for q in q_ref]
        
        if not q_list: 
            st.error(f"Soal untuk {mapel} - {paket} belum tersedia."); return False
        
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

# --- 5. HALAMAN UTAMA ---

def login_page():
    st.markdown("<br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("<h1 style='text-align:center; color:#4F46E5;'>🎓 CAT TKA SD</h1>", unsafe_allow_html=True)
        st.markdown("<div style='background:white; padding:30px; border-radius:20px; box-shadow:0 10px 30px rgba(0,0,0,0.1);'>", unsafe_allow_html=True)
        
        tab_in, tab_up = st.tabs(["🔑 Masuk", "📝 Daftar"])
        with tab_in:
            with st.form("login"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                if st.form_submit_button("Masuk", use_container_width=True, type="primary"):
                    if u=="admin" and p=="admin123":
                        st.session_state.update({'logged_in':True, 'role':'admin', 'nama':'Admin', 'username':'admin'})
                        st.query_params["token"] = "admin"; st.rerun()
                    else:
                        users = db.collection('users').where('username','==',u).where('password','==',p).stream()
                        found = False
                        for user in users:
                            d = user.to_dict()
                            st.session_state.update({'logged_in':True, 'role':'siswa', 'nama':d['nama_lengkap'], 'username':d['username']})
                            st.query_params["token"] = d['username']; found = True; st.rerun()
                        if not found: st.error("Akun salah")
        with tab_up:
            with st.form("reg"):
                nu = st.text_input("Username Baru"); nn = st.text_input("Nama Lengkap"); np = st.text_input("Password", type="password")
                if st.form_submit_button("Daftar"):
                    if nu and nn and np:
                        chk = db.collection('users').document(nu).get()
                        if chk.exists: st.error("Username dipakai.")
                        else:
                            db.collection('users').document(nu).set({'username':nu, 'password':np, 'nama_lengkap':nn, 'role':'siswa'})
                            st.success("Berhasil! Silakan Login.")
        st.markdown("</div>", unsafe_allow_html=True)

def admin_dashboard():
    st.markdown(f"<div class='header-bar'><div><h2 style='margin:0'>Admin Panel</h2></div><a href='/?logout=true' style='color:white;text-decoration:none;border:1px solid white;padding:5px 10px;border-radius:5px;'>Keluar</a></div>", unsafe_allow_html=True)
    if st.query_params.get("logout"): st.query_params.clear(); st.session_state.clear(); st.rerun()
    
    t1, t2, t3, t4, t5 = st.tabs(["📊 Statistik", "📝 Input Soal", "📂 Upload Teks", "🛠️ Edit Soal", "👥 Siswa"])
    
    with t1:
        st.subheader("Analisis Hasil")
        results = list(db.collection('results').stream())
        if results:
            df = pd.DataFrame([r.to_dict() for r in results])
            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(f"<div class='stat-box'><div class='stat-val'>{len(df)}</div><div class='stat-lbl'>Total Ujian</div></div>", unsafe_allow_html=True)
            c2.markdown(f"<div class='stat-box'><div class='stat-val'>{df['skor'].mean():.1f}</div><div class='stat-lbl'>Rata-rata</div></div>", unsafe_allow_html=True)
            c3.markdown(f"<div class='stat-box'><div class='stat-val'>{df['skor'].max():.1f}</div><div class='stat-lbl'>Tertinggi</div></div>", unsafe_allow_html=True)
            c4.markdown(f"<div class='stat-box'><div class='stat-val'>{len(df['username'].unique())}</div><div class='stat-lbl'>Siswa</div></div>", unsafe_allow_html=True)
            
            st.divider()
            st.write("##### Grafik Sebaran Nilai")
            chart = alt.Chart(df).mark_bar().encode(
                x=alt.X('skor', bin=True), y='count()', color='mapel'
            ).interactive()
            st.altair_chart(chart, use_container_width=True)
            st.dataframe(df[['tanggal', 'nama', 'mapel', 'paket', 'skor']].sort_values('tanggal', ascending=False), use_container_width=True)
        else: st.info("Belum ada data.")

    with t2:
        st.subheader("Input Soal")
        cm, ct = st.columns(2)
        in_mapel = cm.selectbox("Mapel", ["Matematika", "Bahasa Indonesia"])
        in_tipe = ct.selectbox("Tipe", ["Pilihan Ganda (PG)", "PG Kompleks", "Benar/Salah"])
        in_paket = st.text_input("Paket", "Paket 1")
        with st.form("f_soal"):
            tanya = st.text_area("Pertanyaan"); img = st.file_uploader("Gambar", type=['png','jpg'])
            opsi = []; kunci = None; st.markdown("---")
            if in_tipe == "Pilihan Ganda (PG)":
                cols = st.columns(4)
                opsi = [cols[i].text_input(f"Opsi {chr(65+i)}") for i in range(4)]
                ans = st.radio("Kunci", ["A","B","C","D"], horizontal=True)
                if opsi[0]: kunci = opsi[ord(ans)-65]; rt = 'single'
            elif in_tipe == "PG Kompleks":
                cols = st.columns(2); k_list = []
                for i in range(4):
                    v = cols[i%2].text_input(f"Pil {i+1}"); 
                    if v: opsi.append(v)
                    if cols[i%2].checkbox(f"Benar?", key=f"c{i}"): k_list.append(v)
                kunci = k_list; rt = 'complex'
            elif in_tipe == "Benar/Salah":
                kunci = {}
                for i in range(3):
                    c1, c2 = st.columns([3,1]); p = c1.text_input(f"Pernyataan {i+1}")
                    k = c2.radio(f"Kunci", ["Benar","Salah"], key=f"bs{i}", horizontal=True, label_visibility="collapsed")
                    if p: opsi.append(p); kunci[p] = k
                rt = 'category'
            if st.form_submit_button("Simpan"):
                imd = process_image(img)
                db.collection('questions').add({'mapel':in_mapel, 'paket':in_paket, 'tipe':rt, 'pertanyaan':tanya, 'gambar':imd, 'opsi':json.dumps(opsi), 'kunci_jawaban':json.dumps(kunci)})
                st.success("Disimpan!")

    with t3:
        st.subheader("Upload Teks CSV (|)")
        txt = st.text_area("Paste Teks", height=200)
        if st.button("Proses"):
            try:
                df = pd.read_csv(io.StringIO(txt), sep='|'); cnt=0
                for _, r in df.iterrows():
                    olist = [str(r[c]) for c in ['pilihan_a','pilihan_b','pilihan_c','pilihan_d'] if pd.notna(r[c])]
                    rt='single'; rk=str(r['jawaban_benar']); fk=rk
                    if 'Check' in str(r['tipe']): rt='complex'; fk=[x.strip() for x in rk.split(',')]
                    elif 'Benar' in str(r['tipe']): 
                        rt='category'; ks=[x.strip() for x in rk.split(',')]
                        fk={olist[i]:ks[i] for i in range(len(ks)) if i<len(olist)}
                    db.collection('questions').add({'mapel':r['mapel'], 'paket':'Paket 1', 'tipe':rt, 'pertanyaan':r['pertanyaan'], 'gambar':None, 'opsi':json.dumps(olist), 'kunci_jawaban':json.dumps(fk)})
                    cnt+=1
                st.success(f"{cnt} Soal Masuk!")
            except Exception as e: st.error(str(e))

    with t4:
        fm = st.selectbox("Mapel", ["Matematika", "Bahasa Indonesia"], key="fe"); fp = st.text_input("Paket", "Paket 1", key="fpe")
        qs = list(db.collection('questions').where('mapel','==',fm).where('paket','==',fp).stream())
        if qs:
            q_data = [{'id':q.id, **q.to_dict()} for q in qs]
            sel = st.selectbox("Pilih Soal", range(len(q_data)), format_func=lambda x: q_data[x]['pertanyaan'][:80])
            q = q_data[sel]
            with st.form("ed"):
                nt = st.text_area("Tanya", q['pertanyaan'])
                if q.get('gambar'): st.image(q['gambar'], width=200)
                ni = st.file_uploader("Ganti")
                no = st.text_area("Opsi JSON", q['opsi']); nk = st.text_area("Kunci JSON", q['kunci_jawaban'])
                if st.form_submit_button("Update"):
                    ud = {'pertanyaan':nt, 'opsi':no, 'kunci_jawaban':nk}
                    if ni: ud['gambar'] = process_image(ni)
                    db.collection('questions').document(q['id']).update(ud); st.success("Updated!"); st.rerun()
                if st.form_submit_button("Hapus"): db.collection('questions').document(q['id']).delete(); st.rerun()

    with t5:
        users = list(db.collection('users').where('role','!=','admin').stream())
        st.dataframe(pd.DataFrame([u.to_dict() for u in users])[['username','nama_lengkap']])

def student_dashboard():
    st.markdown(f"<div class='header-bar'><div><h2 style='margin:0'>Halo, {st.session_state['nama']}! 👋</h2></div><a href='/?logout=true' style='color:white;border:1px solid white;padding:5px 10px;border-radius:5px;text-decoration:none;'>Keluar</a></div>", unsafe_allow_html=True)
    if st.query_params.get("logout"): st.query_params.clear(); st.session_state.clear(); st.rerun()
    
    t1, t2 = st.tabs(["📝 Ujian", "📜 Riwayat"])
    
    with t1:
        st.subheader("Pilih Mata Pelajaran")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("<div class='card-dashboard card-mtk'><h3>📐 Matematika</h3><p>Paket Soal Lengkap</p></div>", unsafe_allow_html=True)
            if st.button("Mulai Paket 1", key="m1", type="primary", use_container_width=True):
                if init_exam("Matematika", "Paket 1"): st.rerun()
        with c2:
            st.markdown("<div class='card-dashboard card-indo'><h3>📖 B. Indonesia</h3><p>Segera Hadir</p></div>", unsafe_allow_html=True)
            
    with t2: # FIX: INI PERBAIKAN ERROR MERAH
        st.subheader("Riwayat Ujian")
        # Query yang menyebabkan error "Requires Index" kita ganti dengan filter Python manual
        docs = db.collection('results').where('username', '==', st.session_state['username']).stream()
        
        # Konversi ke list dan sort di Python (Menghindari error index Firestore)
        hist_data = [d.to_dict() for d in docs]
        hist_data.sort(key=lambda x: x['tanggal'], reverse=True)
        
        if hist_data:
            for d in hist_data:
                with st.expander(f"{d['tanggal']} - {d['mapel']} (Skor: {d['skor']:.1f})"):
                    st.write(f"**Nilai Akhir:** {d['skor']:.1f}")
        else:
            st.info("Belum ada riwayat ujian.")

def exam_interface():
    data = st.session_state['exam_data']; order = st.session_state['q_order']; idx = st.session_state['curr_idx']
    rem = data['end_time'] - datetime.now().timestamp()
    if rem <= 0: finish_exam()
    
    st.markdown(f"<div class='timer-float'>⏱️ {int(rem//60)}:{int(rem%60):02d}</div>", unsafe_allow_html=True)
    
    c1,c2 = st.columns([3,1])
    with c2: 
        f = st.columns(3)
        if f[0].button("A-"): st.session_state['font_size']=14; st.rerun()
        if f[1].button("A"): st.session_state['font_size']=18; st.rerun()
        if f[2].button("A+"): st.session_state['font_size']=24; st.rerun()
    
    col_soal, col_nav = st.columns([3, 1])
    
    with col_soal:
        qid = order[idx]
        q_doc = db.collection('questions').document(qid).get()
        if q_doc.exists:
            q = q_doc.to_dict()
            st.markdown(f"<div class='soal-card'><strong>Soal No. {idx+1}</strong><br><br>{q['pertanyaan']}</div>", unsafe_allow_html=True)
            if q.get('gambar'): st.image(q['gambar'])
            
            opsi = json.loads(q['opsi']); ans = st.session_state['answers'].get(qid)
            
            st.write("")
            if q['tipe'] == 'single':
                sel = st.radio("Jawab:", opsi, key=qid, index=opsi.index(ans) if ans in opsi else None)
                if sel: st.session_state['answers'][qid] = sel
            elif q['tipe'] == 'complex':
                st.write("**Pilih Lebih dari Satu:**")
                sel = ans if isinstance(ans, list) else []; new_sel = []
                for o in opsi:
                    if st.checkbox(o, o in sel, key=f"{qid}_{o}"): new_sel.append(o)
                st.session_state['answers'][qid] = new_sel
            elif q['tipe'] == 'category':
                st.write("**Benar/Salah:**")
                sel = ans if isinstance(ans, dict) else {}; new_sel = {}
                for o in opsi:
                    ca, cb = st.columns([3,1]); ca.write(o)
                    v = cb.radio(f"x_{o}", ["Benar","Salah"], key=f"{qid}_{o}", horizontal=True, label_visibility="collapsed", index=0 if sel.get(o)=="Benar" else 1 if sel.get(o)=="Salah" else None)
                    if v: new_sel[o] = v
                st.session_state['answers'][qid] = new_sel
        
        c_prev, c_ragu, c_next = st.columns([1,1,1])
        if idx > 0:
            if c_prev.button("⬅️ Sblm", use_container_width=True): st.session_state['curr_idx'] -= 1; save_realtime(); st.rerun()
        
        is_r = qid in st.session_state['ragu']
        if c_ragu.button(f"{'🟨 Batal Ragu' if is_r else '🟨 Ragu'}", use_container_width=True):
            if is_r: st.session_state['ragu'].remove(qid)
            else: st.session_state['ragu'].append(qid)
            save_realtime(); st.rerun()
            
        if idx < len(order)-1:
            if c_next.button("Lanjut ➡️", type="primary", use_container_width=True): st.session_state['curr_idx'] += 1; save_realtime(); st.rerun()
        else:
            if c_next.button("✅ Selesai", type="primary", use_container_width=True): finish_exam()

    with col_nav:
        st.write("**Nomor Soal**")
        # GRID RAPI 5 KOLOM
        total_q = len(order)
        for i in range(0, total_q, 5):
            cols = st.columns(5)
            for j in range(5):
                q_idx = i + j
                if q_idx < total_q:
                    q_real = order[q_idx]
                    label = str(q_idx+1)
                    if q_idx == idx: label = f"🔵 {q_idx+1}"
                    elif q_real in st.session_state['ragu']: label = f"🟨 {q_idx+1}"
                    elif q_real in st.session_state['answers'] and st.session_state['answers'][q_real]: label = f"✅ {q_idx+1}"
                    
                    if cols[j].button(label, key=f"g_{q_idx}", use_container_width=True):
                        st.session_state['curr_idx'] = q_idx; save_realtime(); st.rerun()

def finish_exam():
    save_realtime()
    sc, det = calculate_score()
    st.session_state.update({'exam_mode':False, 'result_mode':True, 'last_score':sc, 'last_det':det})
    st.rerun()

def result_interface():
    st.balloons(); st.markdown(f"<h1 style='text-align:center;'>Nilai Kamu: {st.session_state['last_score']:.1f}</h1>", unsafe_allow_html=True)
    if st.button("Kembali ke Beranda", use_container_width=True):
        st.session_state['result_mode']=False; st.rerun()
    with st.expander("Lihat Pembahasan"):
        for d in st.session_state['last_det']:
            c = "#d1fae5" if d['benar'] else "#fee2e2"
            st.markdown(f"<div style='background:{c};padding:10px;margin-bottom:5px;border-radius:5px;'><b>{d['tanya']}</b><br>Jawab: {d['jawab']} | Kunci: {d['kunci']}</div>", unsafe_allow_html=True)

if not st.session_state.get('logged_in'): login_page()
else:
    if st.session_state['role'] == 'admin': admin_dashboard()
    else:
        if st.session_state.get('exam_mode'): exam_interface()
        elif st.session_state.get('result_mode'): result_interface()
        else: student_dashboard()
