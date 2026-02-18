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

# --- 1. KONFIGURASI ---
st.set_page_config(page_title="CAT TKA SD", page_icon="🎓", layout="wide", initial_sidebar_state="collapsed")
if 'font_size' not in st.session_state: st.session_state['font_size'] = 18

# --- 2. CSS PREMIUM (STYLE PUSMENDIK) ---
st.markdown(f"""
<style>
    /* VARIASI WARNA */
    :root {{ --primary: #2563eb; --success: #22c55e; --warning: #facc15; --bg: #f8fafc; }}
    
    /* RESET */
    [data-testid="stAppViewContainer"] {{ background-color: var(--bg); color: #333; }}
    [data-testid="stHeader"] {{ display: none; }}
    footer {{ visibility: hidden; }}
    .stDeployButton {{ display: none; }}

    /* HEADER */
    .header-bar {{
        background: linear-gradient(90deg, #1e3a8a, #3b82f6);
        padding: 15px 25px; color: white; border-radius: 0 0 20px 20px;
        box-shadow: 0 4px 10px rgba(0,0,0,0.1); margin-bottom: 20px;
        display: flex; justify-content: space-between; align-items: center;
    }}

    /* KARTU SOAL */
    .soal-card {{
        background: white; padding: 30px; border-radius: 15px;
        border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);
        font-size: {st.session_state['font_size']}px; line-height: 1.8; min-height: 450px;
    }}

    /* TIMER */
    .timer-badge {{
        background: #dbeafe; color: #1e40af; padding: 8px 15px;
        border-radius: 8px; font-weight: bold; font-family: monospace; font-size: 1.1rem;
        border: 1px solid #93c5fd; text-align: center;
    }}

    /* GRID NOMOR (RAPI) */
    .grid-container {{
        background: white; padding: 15px; border-radius: 12px; border: 1px solid #e2e8f0;
    }}
    
    /* ANALISIS HASIL */
    .score-circle {{
        width: 120px; height: 120px; border-radius: 50%;
        background: conic-gradient(#2563eb var(--p), #e2e8f0 0);
        display: flex; align-items: center; justify-content: center; margin: 0 auto;
    }}
    .score-inner {{
        width: 100px; height: 100px; background: white; border-radius: 50%;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
    }}
    .topic-badge {{
        padding: 5px 10px; border-radius: 5px; font-size: 0.9rem; margin-bottom: 5px; display: block;
    }}
    .bg-green {{ background: #dcfce7; color: #166534; border: 1px solid #86efac; }}
    .bg-red {{ background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; }}

</style>
""", unsafe_allow_html=True)

# --- 3. DATABASE ---
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
if not db: st.error("Database Error."); st.stop()

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
        if data.get('status') == 'ongoing':
            now = datetime.now().timestamp()
            if now < data.get('end_time', 0):
                st.session_state.update({
                    'exam_data': data, 'q_order': json.loads(data['q_order']),
                    'answers': json.loads(data['answers']), 'ragu': json.loads(data.get('ragu', '[]')),
                    'curr_idx': 0, 'exam_mode': True
                })
                start_new = False
                st.toast("Melanjutkan sesi...", icon="🔄")
    
    if start_new:
        q_ref = db.collection('questions').where('mapel', '==', mapel).where('paket', '==', paket).stream()
        q_list = [{'id': q.id, **q.to_dict()} for q in q_ref]
        
        if not q_list: st.error("Soal tidak ditemukan."); return False
        
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
    score = 0
    topic_stats = {} # Analisis Topik
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
        
        # Analisis Topik (PENTING BUAT GRAFIK)
        topik = q.get('topik', 'Umum')
        if topik not in topic_stats: topic_stats[topik] = {'correct':0, 'total':0}
        topic_stats[topik]['total'] += 1
        if is_correct: topic_stats[topik]['correct'] += 1
        
        details.append({'tanya': q['pertanyaan'], 'jawab': user_ans, 'kunci': key, 'benar': is_correct, 'topik': topik})
        
    final = (score / len(q_ids)) * 100
    
    sid = f"{st.session_state['username']}_{st.session_state['exam_data']['mapel']}_{st.session_state['exam_data']['paket']}"
    db.collection('exam_sessions').document(sid).update({'status': 'completed', 'score': final})
    
    db.collection('results').add({
        'username': st.session_state['username'], 'nama': st.session_state['nama'],
        'mapel': st.session_state['exam_data']['mapel'], 'paket': st.session_state['exam_data']['paket'],
        'skor': final, 'tanggal': datetime.now().strftime("%Y-%m-%d %H:%M"),
        'details': json.dumps(details, default=str),
        'topic_analysis': json.dumps(topic_stats)
    })
    return final, details, topic_stats

# --- 5. PAGE FUNCTIONS ---

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
                        if not found: st.error("Akun salah")
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
    st.markdown(f"<div class='header-bar'><div><b>Dashboard Guru</b></div><a href='/?logout=true' style='color:white;border:1px solid white;padding:5px 15px;border-radius:10px;text-decoration:none;'>Keluar</a></div>", unsafe_allow_html=True)
    if st.query_params.get("logout"): st.query_params.clear(); st.session_state.clear(); st.rerun()
    
    t1, t2, t3, t4, t5 = st.tabs(["📊 Analisis", "📝 Input", "📂 Upload", "🛠️ Edit", "👥 Siswa"])
    
    with t1:
        st.subheader("Statistik Kelas")
        results = list(db.collection('results').stream())
        if results:
            df = pd.DataFrame([r.to_dict() for r in results])
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Ujian", len(df))
            c2.metric("Rata-Rata", f"{df['skor'].mean():.1f}")
            c3.metric("Tertinggi", f"{df['skor'].max():.1f}")
            c4.metric("Siswa Aktif", len(df['username'].unique()))
            
            st.divider()
            c_a, c_b = st.columns([2,1])
            with c_a:
                st.write("##### Grafik Sebaran Nilai")
                ch = alt.Chart(df).mark_bar().encode(x=alt.X('skor', bin=True), y='count()', color='mapel').interactive()
                st.altair_chart(ch, use_container_width=True)
            with c_b:
                st.write("##### Peringkat")
                st.dataframe(df[['nama','skor']].sort_values('skor',ascending=False).head(10), hide_index=True)
        else: st.info("Belum ada data.")

    with t2:
        c1, c2 = st.columns(2)
        in_mapel = c1.selectbox("Mapel", ["Matematika", "Bahasa Indonesia"])
        in_tipe = c2.selectbox("Tipe", ["Pilihan Ganda (PG)", "PG Kompleks", "Benar/Salah"])
        in_paket = st.text_input("Paket", "Paket 1")
        in_topik = st.text_input("Topik", "Umum")
        
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
                db.collection('questions').add({'mapel':in_mapel, 'paket':in_paket, 'tipe':rt, 'topik':in_topik,'pertanyaan':tanya, 'gambar':imd, 'opsi':json.dumps(opsi), 'kunci_jawaban':json.dumps(kunci)})
                st.success("Tersimpan!")

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

    with t4:
        fm=st.selectbox("M", ["Matematika", "Bahasa Indonesia"], key="f"); fp=st.text_input("P", "Paket 1", key="fp")
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

    with t5:
        us=list(db.collection('users').where('role','!=','admin').stream())
        st.dataframe(pd.DataFrame([u.to_dict() for u in us])[['username','nama_lengkap']])

def student_dashboard():
    st.markdown(f"<div class='header-bar'><div>Halo, <b>{st.session_state['nama']}</b></div><a href='/?logout=true' style='color:white;border:1px solid white;padding:5px 15px;border-radius:20px;text-decoration:none;'>Keluar</a></div>", unsafe_allow_html=True)
    if st.query_params.get("logout"): st.query_params.clear(); st.session_state.clear(); st.rerun()
    
    t1, t2 = st.tabs(["📝 Ujian", "📜 Riwayat"])
    
    with t1:
        c1, c2 = st.columns(2)
        with c1:
            st.info("📐 Matematika")
            if st.button("Mulai Paket 1", key="m1", type="primary", use_container_width=True):
                if init_exam("Matematika", "Paket 1"): st.rerun()
        with c2:
            st.success("📖 B. Indonesia")
            st.button("Segera Hadir", disabled=True, use_container_width=True)
    
    with t2:
        res = db.collection('results').where('username', '==', st.session_state['username']).stream()
        hist = sorted([r.to_dict() for r in res], key=lambda x: x['tanggal'], reverse=True)
        if hist:
            for h in hist:
                with st.expander(f"{h['tanggal']} | {h['mapel']} | Skor: {h['skor']:.1f}"):
                    if 'topic_analysis' in h:
                        stats = json.loads(h['topic_analysis'])
                        for k, v in stats.items():
                            st.progress(v['correct']/v['total'] if v['total']>0 else 0, text=f"{k}: {v['correct']}/{v['total']} Benar")
        else: st.info("Belum ada riwayat.")

def exam_interface():
    data = st.session_state['exam_data']; order = st.session_state['q_order']; idx = st.session_state['curr_idx']
    rem = data['end_time'] - datetime.now().timestamp()
    if rem <= 0: finish_exam()
    
    # Header
    c1,c2,c3 = st.columns([6,3,3])
    with c1: st.markdown(f"**{data['mapel']}** | No. {idx+1}")
    with c2: st.markdown(f"<div class='timer-badge'>⏱️ {int(rem//60)}:{int(rem%60):02d}</div>", unsafe_allow_html=True)
    with c3: 
        f = st.columns(3)
        if f[0].button("A-"): st.session_state['font_size']=14; st.rerun()
        if f[1].button("A"): st.session_state['font_size']=18; st.rerun()
        if f[2].button("A+"): st.session_state['font_size']=24; st.rerun()
    
    # LAYOUT UTAMA (RESPONSIF)
    col_soal, col_nav = st.columns([3, 1])
    
    with col_soal:
        qid = order[idx]
        q_doc = db.collection('questions').document(qid).get()
        if q_doc.exists:
            q = q_doc.to_dict()
            st.markdown(f"<div class='soal-card'>", unsafe_allow_html=True)
            st.write(q['pertanyaan'])
            if q.get('gambar'): st.image(q['gambar'])
            st.markdown("<hr>", unsafe_allow_html=True)
            
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
        
        # Navigasi Bawah
        st.markdown("<br>", unsafe_allow_html=True)
        c_prev, c_ragu, c_next = st.columns([1,1,1])
        if idx > 0:
            if c_prev.button("⬅️ Sebelumnya", use_container_width=True): st.session_state['curr_idx'] -= 1; save_realtime(); st.rerun()
        is_r = qid in st.session_state['ragu']
        if c_ragu.button(f"{'🟨 Batal Ragu' if is_r else '🟨 Ragu'}", use_container_width=True):
            if is_r: st.session_state['ragu'].remove(qid)
            else: st.session_state['ragu'].append(qid)
            save_realtime(); st.rerun()
        if idx < len(order)-1:
            if c_next.button("Selanjutnya ➡️", type="primary", use_container_width=True): st.session_state['curr_idx'] += 1; save_realtime(); st.rerun()
        else:
            if c_next.button("✅ Selesai", type="primary", use_container_width=True): finish_exam()

    # Grid Nomor Soal Rapi (5 Kolom)
    with col_nav:
        st.write("**Navigasi Soal**")
        st.markdown("<div class='grid-container'>", unsafe_allow_html=True)
        total = len(order)
        rows = (total + 4) // 5
        for r in range(rows):
            cols = st.columns(5)
            for c in range(5):
                q_idx = r * 5 + c
                if q_idx < total:
                    qid_real = order[q_idx]
                    label = str(q_idx+1)
                    type_btn = "secondary"
                    if q_idx == idx: label = f"🔵"
                    elif qid_real in st.session_state['ragu']: label = f"🟨"
                    elif qid_real in st.session_state['answers'] and st.session_state['answers'][qid_real]: label = f"✅"
                    
                    if cols[c].button(label, key=f"g_{q_idx}", help=f"No {q_idx+1}"):
                        st.session_state['curr_idx'] = q_idx; save_realtime(); st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

def finish_exam():
    save_realtime()
    sc, det, stats = calculate_score()
    st.session_state.update({'exam_mode':False, 'result_mode':True, 'last_score':sc, 'last_det':det, 'last_stats':stats})
    st.rerun()

def result_interface():
    st.balloons()
    score = st.session_state['last_score']
    stats = st.session_state.get('last_stats', {})
    
    # CARD NILAI LINGKARAN (CSS GRADIENT)
    st.markdown(f"""
    <div style='text-align:center; padding:30px; background:white; border-radius:15px; box-shadow:0 5px 15px rgba(0,0,0,0.1);'>
        <div class='score-circle' style='--p: {score*3.6}deg'>
            <div class='score-inner'>
                <h1 style='color:#2563eb; margin:0; font-size:2.5rem;'>{score:.0f}</h1>
                <small>Skor Akhir</small>
            </div>
        </div>
    </div>
    <br>
    """, unsafe_allow_html=True)
    
    # ANALISIS MATERI
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("✅ Materi Kuat")
        found=False
        for k,v in stats.items():
            if v['total']>0 and (v['correct']/v['total']) >= 0.7:
                st.markdown(f"<div class='topic-badge bg-green'>{k} ({v['correct']}/{v['total']} Benar)</div>", unsafe_allow_html=True)
                found=True
        if not found: st.write("-")
    
    with c2:
        st.subheader("⚠️ Perlu Ditingkatkan")
        found=False
        for k,v in stats.items():
            if v['total']>0 and (v['correct']/v['total']) < 0.7:
                st.markdown(f"<div class='topic-badge bg-red'>{k} ({v['correct']}/{v['total']} Benar)</div>", unsafe_allow_html=True)
                found=True
        if not found: st.write("Kerja bagus! Pertahankan.")

    if st.button("Kembali ke Beranda", use_container_width=True):
        st.session_state['result_mode']=False; st.rerun()

# Main Loop
if not st.session_state.get('logged_in'): login_page()
else:
    if st.session_state['role'] == 'admin': admin_dashboard()
    else:
        if st.session_state.get('exam_mode'): exam_interface()
        elif st.session_state.get('result_mode'): result_interface()
        else: student_dashboard()
