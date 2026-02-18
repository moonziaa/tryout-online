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

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(
    page_title="CAT TKA SD", 
    page_icon="🎓", 
    layout="wide", 
    initial_sidebar_state="collapsed"
)

# Inisialisasi Ukuran Font Default
if 'font_size' not in st.session_state: st.session_state['font_size'] = 18

# --- 2. CSS CUSTOM (STYLE PUSMENDIK PREMIUM) ---
st.markdown(f"""
<style>
    /* VARIABEL WARNA */
    :root {{
        --primary: #2563eb;
        --secondary: #facc15;
        --success: #22c55e;
        --bg-body: #f8fafc;
        --card-bg: #ffffff;
        --text-main: #1e293b;
    }}

    /* RESET STREAMLIT */
    [data-testid="stAppViewContainer"] {{ background-color: var(--bg-body); color: var(--text-main); }}
    [data-testid="stHeader"] {{ display: none; }}
    footer {{ visibility: hidden; }}
    .stDeployButton {{ display: none; }}
    
    /* HEADER CUSTOM (Atas) */
    .pusmendik-header {{
        background: linear-gradient(90deg, #1e3a8a 0%, #3b82f6 100%);
        padding: 15px 25px;
        color: white;
        border-radius: 0 0 15px 15px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        display: flex; justify-content: space-between; align-items: center;
        margin-bottom: 20px;
    }}
    
    /* CARD SOAL (Wadah Pertanyaan) */
    .soal-card {{
        background-color: white;
        padding: 30px;
        border-radius: 12px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);
        font-size: {st.session_state['font_size']}px;
        line-height: 1.8;
        min-height: 450px;
        position: relative;
    }}
    
    /* TOMBOL NAVIGASI BAWAH (Prev/Next) */
    .nav-bottom-bar {{
        display: flex; 
        justify-content: space-between; 
        align-items: center;
        margin-top: 20px;
        padding-top: 20px;
        border-top: 1px solid #e2e8f0;
    }}
    
    /* GRID NOMOR SOAL (Kanan/Bawah) */
    .grid-container {{
        background: white;
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #e2e8f0;
    }}
    
    /* TIMER (Kanan Atas) */
    .timer-badge {{
        background-color: #dbeafe;
        color: #1e40af;
        padding: 8px 15px;
        border-radius: 20px;
        font-weight: bold;
        font-family: monospace;
        font-size: 16px;
        border: 1px solid #93c5fd;
    }}

    /* TOMBOL-TOMBOL KHUSUS */
    .btn-ragu {{ background-color: #fef08a !important; color: #854d0e !important; border: 1px solid #facc15 !important; }}
    
    /* ANALISIS SCORE */
    .score-circle {{
        width: 150px; height: 150px;
        border-radius: 50%;
        background: conic-gradient(#2563eb {st.session_state.get('last_score', 0)}%, #e2e8f0 0);
        display: flex; align-items: center; justify-content: center;
        margin: 0 auto;
    }}
    .score-inner {{
        width: 130px; height: 130px;
        background: white; border-radius: 50%;
        display: flex; flex-direction: column;
        align-items: center; justify-content: center;
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
if not db: st.error("Koneksi Database Bermasalah. Cek Secrets!"); st.stop()

# --- 4. LOGIC SISTEM ---
def auto_login():
    """Cek sesi login agar tidak logout saat refresh"""
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
    """Memulai sesi ujian (Baru atau Lanjut)"""
    session_id = f"{st.session_state['username']}_{mapel}_{paket}"
    doc_ref = db.collection('exam_sessions').document(session_id)
    doc = doc_ref.get()
    
    start_new = True
    
    # Cek apakah ada sesi menggantung yang belum selesai (Ongoing)
    if doc.exists:
        data = doc.to_dict()
        if data.get('status') == 'ongoing':
            now = datetime.now().timestamp()
            # Jika waktu masih ada, lanjutkan (Resume)
            if now < data.get('end_time', 0):
                st.session_state.update({
                    'exam_data': data, 'q_order': json.loads(data['q_order']),
                    'answers': json.loads(data['answers']), 'ragu': json.loads(data.get('ragu', '[]')),
                    'curr_idx': 0, 'exam_mode': True
                })
                start_new = False
                st.toast("Melanjutkan sesi ujian...", icon="🔄")
    
    # Jika tidak ada sesi ongoing (atau sudah selesai), buat BARU (Retake)
    if start_new:
        q_ref = db.collection('questions').where('mapel', '==', mapel).where('paket', '==', paket).stream()
        q_list = [{'id': q.id, **q.to_dict()} for q in q_ref]
        
        if not q_list: 
            st.error(f"Soal {paket} belum tersedia."); return False
        
        random.shuffle(q_list)
        q_order = [q['id'] for q in q_list]
        start_ts = datetime.now().timestamp()
        
        new_data = {
            'username': st.session_state['username'], 'mapel': mapel, 'paket': paket,
            'start_time': start_ts, 'end_time': start_ts + (75*60),
            'q_order': json.dumps(q_order), 'answers': "{}", 'ragu': "[]",
            'status': 'ongoing', 'score': 0
        }
        # Timpa sesi lama agar bisa ujian ulang
        doc_ref.set(new_data)
        st.session_state.update({
            'exam_data': new_data, 'q_order': q_order, 'answers': {}, 'ragu': [], 'curr_idx': 0, 'exam_mode': True
        })
        st.toast("Ujian dimulai!", icon="🚀")
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
    score = 0
    topic_stats = {} # Untuk analisis topik
    details = []
    
    for qid in q_ids:
        q_doc = db.collection('questions').document(qid).get()
        if not q_doc.exists: continue
        q = q_doc.to_dict()
        user_ans = ans.get(qid)
        try: key = json.loads(q['kunci_jawaban'])
        except: key = q['kunci_jawaban']
        
        # Penilaian
        is_correct = False
        if q['tipe'] == 'single' and user_ans == key: is_correct = True
        elif q['tipe'] == 'complex' and user_ans and set(user_ans) == set(key): is_correct = True
        elif q['tipe'] == 'category' and user_ans == key: is_correct = True
        
        if is_correct: score += 1
        
        # Analisis Topik
        topik = q.get('topik', 'Umum') # Pastikan kolom topik ada di inputan
        if topik not in topic_stats: topic_stats[topik] = {'correct': 0, 'total': 0}
        topic_stats[topik]['total'] += 1
        if is_correct: topic_stats[topik]['correct'] += 1
        
        details.append({'tanya': q['pertanyaan'], 'jawab': user_ans, 'kunci': key, 'benar': is_correct, 'topik': topik})
        
    final = (score / len(q_ids)) * 100
    
    # Update status sesi
    sid = f"{st.session_state['username']}_{st.session_state['exam_data']['mapel']}_{st.session_state['exam_data']['paket']}"
    db.collection('exam_sessions').document(sid).update({'status': 'completed', 'score': final})
    
    # Simpan ke riwayat
    db.collection('results').add({
        'username': st.session_state['username'], 'nama': st.session_state['nama'],
        'mapel': st.session_state['exam_data']['mapel'], 'paket': st.session_state['exam_data']['paket'],
        'skor': final, 'tanggal': datetime.now().strftime("%Y-%m-%d %H:%M"),
        'details': json.dumps(details, default=str),
        'topic_analysis': json.dumps(topic_stats)
    })
    return final, details, topic_stats

# --- 5. HALAMAN UTAMA ---

def login_page():
    st.markdown("<br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("<h1 style='text-align:center; color:#2563eb;'>🎓 CAT TKA SD</h1>", unsafe_allow_html=True)
        st.markdown("<div style='background:white; padding:30px; border-radius:15px; box-shadow:0 10px 30px rgba(0,0,0,0.1);'>", unsafe_allow_html=True)
        
        t1, t2 = st.tabs(["Masuk", "Daftar"])
        with t1:
            with st.form("l"):
                u = st.text_input("Username"); p = st.text_input("Password", type="password")
                if st.form_submit_button("Masuk", use_container_width=True, type="primary"):
                    if u=="admin" and p=="admin123":
                        st.session_state.update({'logged_in':True, 'role':'admin', 'nama':'Admin', 'username':'admin'})
                        st.query_params["token"]="admin"; st.rerun()
                    else:
                        users = db.collection('users').where('username','==',u).where('password','==',p).stream()
                        found = False
                        for user in users:
                            d = user.to_dict()
                            st.session_state.update({'logged_in':True, 'role':'siswa', 'nama':d['nama_lengkap'], 'username':d['username']})
                            st.query_params["token"]=d['username']; found=True; st.rerun()
                        if not found: st.error("Akun tidak ditemukan")
        with t2:
            with st.form("r"):
                nu = st.text_input("Username Baru"); nn = st.text_input("Nama Lengkap"); np = st.text_input("Password", type="password")
                if st.form_submit_button("Daftar"):
                    if nu and nn and np:
                        if db.collection('users').document(nu).get().exists: st.error("Username dipakai.")
                        else:
                            db.collection('users').document(nu).set({'username':nu,'password':np,'nama_lengkap':nn,'role':'siswa'})
                            st.success("Berhasil! Silakan Login.")
        st.markdown("</div>", unsafe_allow_html=True)

def admin_dashboard():
    st.markdown(f"<div class='pusmendik-header'><div><b>Dashboard Guru</b></div><a href='/?logout=true' style='color:white;text-decoration:none;border:1px solid white;padding:5px 10px;border-radius:5px;'>Keluar</a></div>", unsafe_allow_html=True)
    if st.query_params.get("logout"): st.query_params.clear(); st.session_state.clear(); st.rerun()
    
    t1, t2, t3, t4, t5 = st.tabs(["📊 Statistik", "📝 Input Soal", "📂 Upload Teks", "🛠️ Edit Soal", "👥 Siswa"])
    
    with t1:
        st.subheader("Statistik Nilai Siswa")
        results = list(db.collection('results').stream())
        if results:
            df = pd.DataFrame([r.to_dict() for r in results])
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Ujian", len(df))
            c2.metric("Rata-Rata", f"{df['skor'].mean():.1f}")
            c3.metric("Tertinggi", f"{df['skor'].max():.1f}")
            c4.metric("Terendah", f"{df['skor'].min():.1f}")
            
            st.divider()
            col_chart, col_data = st.columns([2,1])
            with col_chart:
                st.write("##### Sebaran Nilai")
                chart = alt.Chart(df).mark_bar().encode(
                    x=alt.X('skor', bin=True, title='Rentang Nilai'),
                    y='count()',
                    color='mapel',
                    tooltip=['nama', 'skor']
                ).interactive()
                st.altair_chart(chart, use_container_width=True)
            with col_data:
                st.write("##### Peringkat")
                st.dataframe(df[['nama','skor']].sort_values('skor', ascending=False).head(10), hide_index=True)
        else: st.info("Belum ada data.")

    # Input Soal Manual (Dinamis)
    with t2:
        c1, c2 = st.columns(2)
        in_mapel = c1.selectbox("Mapel", ["Matematika", "Bahasa Indonesia"])
        in_tipe = c2.selectbox("Tipe", ["Pilihan Ganda (PG)", "PG Kompleks", "Benar/Salah"])
        in_paket = st.text_input("Paket", "Paket 1")
        in_topik = st.text_input("Topik Materi", "Umum", help="Contoh: Bilangan, Geometri, Teks Fiksi")
        
        with st.form("add"):
            tanya = st.text_area("Pertanyaan")
            img = st.file_uploader("Gambar", type=['png','jpg'])
            opsi=[]; kunci=None; st.markdown("---")
            
            if in_tipe=="Pilihan Ganda (PG)":
                cols=st.columns(4); opsi=[cols[i].text_input(f"Op {chr(65+i)}") for i in range(4)]
                k=st.radio("Kunci", ["A","B","C","D"], horizontal=True)
                if opsi[0]: kunci=opsi[ord(k)-65]; rt='single'
            elif in_tipe=="PG Kompleks":
                cols=st.columns(2); kl=[]
                for i in range(4):
                    v=cols[i%2].text_input(f"P {i+1}")
                    if v: opsi.append(v)
                    if cols[i%2].checkbox("Benar?", key=f"c{i}"): kl.append(v)
                kunci=kl; rt='complex'
            elif in_tipe=="Benar/Salah":
                kunci={}
                for i in range(3):
                    c1,c2=st.columns([3,1]); p=c1.text_input(f"Pernyataan {i+1}")
                    k=c2.radio("K", ["Benar","Salah"], key=f"b{i}", horizontal=True, label_visibility="collapsed")
                    if p: opsi.append(p); kunci[p]=k
                rt='category'
                
            if st.form_submit_button("Simpan"):
                imd = process_image(img)
                db.collection('questions').add({
                    'mapel':in_mapel, 'paket':in_paket, 'tipe':rt, 'topik':in_topik,
                    'pertanyaan':tanya, 'gambar':imd, 'opsi':json.dumps(opsi), 'kunci_jawaban':json.dumps(kunci)
                })
                st.success("Tersimpan!")

    # Upload Teks
    with t3:
        txt = st.text_area("Paste CSV (|)", height=150)
        if st.button("Upload"):
            try:
                df=pd.read_csv(io.StringIO(txt), sep='|'); cnt=0
                for _,r in df.iterrows():
                    o=[str(r[c]) for c in ['pilihan_a','pilihan_b','pilihan_c','pilihan_d'] if pd.notna(r[c])]
                    rt='single'; rk=str(r['jawaban_benar']); fk=rk
                    if 'Check' in str(r['tipe']): rt='complex'; fk=[x.strip() for x in rk.split(',')]
                    elif 'Benar' in str(r['tipe']): rt='category'; ks=[x.strip() for x in rk.split(',')]; fk={o[i]:ks[i] for i in range(len(ks)) if i<len(o)}
                    db.collection('questions').add({'mapel':r['mapel'],'paket':'Paket 1','topik':str(r.get('topik','Umum')),'tipe':rt,'pertanyaan':r['pertanyaan'],'gambar':None,'opsi':json.dumps(o),'kunci_jawaban':json.dumps(fk)})
                    cnt+=1
                st.success(f"{cnt} Sukses")
            except Exception as e: st.error(str(e))

    # Edit Soal
    with t4:
        fm=st.selectbox("M", ["Matematika","Bahasa Indonesia"], key="f"); fp=st.text_input("P", "Paket 1", key="fp")
        qs=list(db.collection('questions').where('mapel','==',fm).where('paket','==',fp).stream())
        if qs:
            qdat=[{'id':q.id, **q.to_dict()} for q in qs]
            sel=st.selectbox("Pilih", range(len(qdat)), format_func=lambda x: qdat[x]['pertanyaan'][:60])
            q=qdat[sel]
            with st.form("eds"):
                nt=st.text_area("Tanya", q['pertanyaan'])
                ntop=st.text_input("Topik", q.get('topik','Umum'))
                if q.get('gambar'): st.image(q['gambar'], width=150)
                ni=st.file_uploader("Ganti Gambar")
                c1,c2=st.columns(2)
                if c1.form_submit_button("Update"):
                    ud={'pertanyaan':nt, 'topik':ntop}
                    if ni: ud['gambar']=process_image(ni)
                    db.collection('questions').document(q['id']).update(ud); st.rerun()
                if c2.form_submit_button("Hapus"): db.collection('questions').document(q['id']).delete(); st.rerun()

    # Siswa
    with t5:
        us=list(db.collection('users').where('role','!=','admin').stream())
        st.dataframe(pd.DataFrame([u.to_dict() for u in us])[['username','nama_lengkap']])

def student_dashboard():
    st.markdown(f"<div class='pusmendik-header'><div>Halo, <b>{st.session_state['nama']}</b></div><a href='/?logout=true' style='color:white;text-decoration:none;border:1px solid white;padding:5px 15px;border-radius:20px;font-size:14px;'>Keluar</a></div>", unsafe_allow_html=True)
    if st.query_params.get("logout"): st.query_params.clear(); st.session_state.clear(); st.rerun()
    
    t1, t2 = st.tabs(["📝 Ujian", "📜 Riwayat"])
    
    with t1:
        st.subheader("Pilih Paket Soal")
        c1, c2 = st.columns(2)
        with c1:
            with st.container(border=True):
                st.markdown("### 📐 Matematika")
                st.caption("30 Soal | 75 Menit")
                if st.button("Mulai Paket 1", key="m1", type="primary", use_container_width=True):
                    if init_exam("Matematika", "Paket 1"): st.rerun()
        with c2:
            with st.container(border=True):
                st.markdown("### 📖 B. Indonesia")
                st.caption("Segera Hadir")
                st.button("Belum Tersedia", disabled=True, use_container_width=True)
    
    with t2:
        st.subheader("Riwayat Nilai")
        # Fix query error by client-side filtering
        res = db.collection('results').where('username', '==', st.session_state['username']).stream()
        hist = sorted([r.to_dict() for r in res], key=lambda x: x['tanggal'], reverse=True)
        
        if hist:
            for h in hist:
                with st.expander(f"{h['mapel']} - {h['tanggal']} (Skor: {h['skor']:.1f})"):
                    # Tampilkan analisis topik sederhana
                    if 'topic_analysis' in h:
                        stats = json.loads(h['topic_analysis'])
                        st.write("**Analisis Topik:**")
                        for k, v in stats.items():
                            st.progress(v['correct']/v['total'], text=f"{k}: {v['correct']}/{v['total']} Benar")
        else: st.info("Belum ada riwayat.")

def exam_interface():
    data = st.session_state['exam_data']; order = st.session_state['q_order']; idx = st.session_state['curr_idx']
    rem = data['end_time'] - datetime.now().timestamp()
    if rem <= 0: finish_exam()
    
    # HEADER UJIAN
    c1,c2,c3 = st.columns([6,3,3])
    with c1: st.markdown(f"**{data['mapel']}** | No. {idx+1}")
    with c2: st.markdown(f"<div class='timer-badge'>⏱️ {int(rem//60)}:{int(rem%60):02d}</div>", unsafe_allow_html=True)
    with c3: 
        f = st.columns(3)
        if f[0].button("A-"): st.session_state['font_size']=14; st.rerun()
        if f[1].button("A"): st.session_state['font_size']=18; st.rerun()
        if f[2].button("A+"): st.session_state['font_size']=24; st.rerun()
    
    # LAYOUT RESPONSIVE (Grid Pindah ke Bawah di Mobile otomatis oleh Streamlit)
    col_soal, col_nav = st.columns([3, 1])
    
    # --- AREA SOAL ---
    with col_soal:
        qid = order[idx]
        q_doc = db.collection('questions').document(qid).get()
        if q_doc.exists:
            q = q_doc.to_dict()
            st.markdown(f"<div class='soal-card'>", unsafe_allow_html=True)
            st.write(q['pertanyaan'])
            if q.get('gambar'): st.image(q['gambar'])
            st.markdown("<hr>", unsafe_allow_html=True)
            
            # Render Jawaban
            opsi = json.loads(q['opsi']); ans = st.session_state['answers'].get(qid)
            
            if q['tipe'] == 'single':
                sel = st.radio("Jawab:", opsi, key=qid, index=opsi.index(ans) if ans in opsi else None)
                if sel: st.session_state['answers'][qid] = sel
            elif q['tipe'] == 'complex':
                st.caption("Pilih lebih dari satu:")
                sel = ans if isinstance(ans, list) else []; new_sel = []
                for o in opsi:
                    if st.checkbox(o, o in sel, key=f"{qid}_{o}"): new_sel.append(o)
                st.session_state['answers'][qid] = new_sel
            elif q['tipe'] == 'category':
                st.caption("Tentukan Benar/Salah:")
                sel = ans if isinstance(ans, dict) else {}; new_sel = {}
                for o in opsi:
                    ca, cb = st.columns([3,1]); ca.write(o)
                    v = cb.radio("pilih", ["Benar","Salah"], key=f"{qid}_{o}", horizontal=True, label_visibility="collapsed", index=0 if sel.get(o)=="Benar" else 1 if sel.get(o)=="Salah" else None)
                    if v: new_sel[o] = v
                st.session_state['answers'][qid] = new_sel
            st.markdown("</div>", unsafe_allow_html=True)
        
        # NAVIGASI BAWAH
        st.markdown("<br>", unsafe_allow_html=True)
        c_prev, c_ragu, c_next = st.columns([1,1,1])
        
        # Tombol Navigasi Cerdas
        if idx > 0:
            if c_prev.button("⬅️ Sebelumnya", use_container_width=True):
                st.session_state['curr_idx'] -= 1; save_realtime(); st.rerun()
        else:
            c_prev.write("") # Spacer
            
        is_r = qid in st.session_state['ragu']
        if c_ragu.button(f"{'🟨 Batal Ragu' if is_r else '🟨 Ragu'}", use_container_width=True):
            if is_r: st.session_state['ragu'].remove(qid)
            else: st.session_state['ragu'].append(qid)
            save_realtime(); st.rerun()
            
        if idx < len(order)-1:
            if c_next.button("Selanjutnya ➡️", type="primary", use_container_width=True):
                st.session_state['curr_idx'] += 1; save_realtime(); st.rerun()
        else:
            if c_next.button("✅ Selesai", type="primary", use_container_width=True):
                finish_exam()

    # --- GRID NOMOR (KANAN/BAWAH) ---
    with col_nav:
        st.write("**Navigasi Soal**")
        st.markdown("<div class='grid-container'>", unsafe_allow_html=True)
        
        # Grid 5 Kolom
        total_q = len(order)
        for i in range(0, total_q, 5):
            cols = st.columns(5)
            for j in range(5):
                q_idx = i + j
                if q_idx < total_q:
                    q_real = order[q_idx]
                    label = str(q_idx+1)
                    
                    # Logika Warna Tombol
                    type_btn = "secondary"
                    if q_idx == idx: 
                        label = f"🔵 {q_idx+1}" # Aktif
                        type_btn = "primary"
                    elif q_real in st.session_state['ragu']:
                        label = f"🟨 {q_idx+1}" # Ragu
                    elif q_real in st.session_state['answers'] and st.session_state['answers'][q_real]:
                        label = f"✅ {q_idx+1}" # Sudah dijawab
                    
                    if cols[j].button(label, key=f"g_{q_idx}", help=f"No {q_idx+1}"):
                        st.session_state['curr_idx'] = q_idx; save_realtime(); st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        st.caption("🔵: Aktif | ✅: Dijawab | 🟨: Ragu")

def finish_exam():
    save_realtime()
    sc, det, stats = calculate_score()
    st.session_state.update({'exam_mode':False, 'result_mode':True, 'last_score':sc, 'last_det':det, 'last_stats':stats})
    st.rerun()

def result_interface():
    st.balloons()
    score = st.session_state['last_score']
    
    # Tampilan Hasil Premium
    c_score, c_stat = st.columns([1, 2])
    
    with c_score:
        st.markdown(f"""
        <div style='text-align:center;'>
            <div class='score-circle'>
                <div class='score-inner'>
                    <h1 style='color:#2563eb; font-size:40px; margin:0;'>{score:.1f}</h1>
                    <small>Nilai Akhir</small>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("Kembali ke Beranda", use_container_width=True):
            st.session_state['result_mode']=False; st.rerun()

    with c_stat:
        st.subheader("Analisis Kemampuan")
        stats = st.session_state.get('last_stats', {})
        
        if stats:
            # Pisahkan Materi Kuat dan Lemah
            kuat = [k for k,v in stats.items() if (v['correct']/v['total']) >= 0.7]
            lemah = [k for k,v in stats.items() if (v['correct']/v['total']) < 0.5]
            
            if kuat:
                st.success(f"💪 **Materi Kuat:** {', '.join(kuat)}")
            if lemah:
                st.error(f"⚠️ **Perlu Belajar Lagi:** {', '.join(lemah)}")
                st.markdown("**Rekomendasi:** Fokus pelajari kembali materi di atas agar nilaimu meningkat.")
            
            # Grafik Batang Performa Topik
            data_chart = [{"Topik": k, "Persentase": (v['correct']/v['total'])*100} for k,v in stats.items()]
            st.bar_chart(pd.DataFrame(data_chart).set_index("Topik"))

    st.divider()
    with st.expander("Lihat Pembahasan Lengkap"):
        for d in st.session_state['last_det']:
            bg = "#dcfce7" if d['benar'] else "#fee2e2"
            icon = "✅" if d['benar'] else "❌"
            st.markdown(f"""
            <div style='background:{bg}; padding:15px; border-radius:10px; margin-bottom:10px; color:black;'>
                <small>{d.get('topik','Umum')}</small><br>
                <strong>{icon} {d['tanya']}</strong><br>
                <div style='margin-top:5px; font-size:0.9em; color:#333;'>
                    Jawabanmu: <b>{d['jawab']}</b> | Kunci: <b>{d['kunci']}</b>
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
