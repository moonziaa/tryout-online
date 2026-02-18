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
st.set_page_config(page_title="CAT TKA SD", page_icon="🎓", layout="wide", initial_sidebar_state="collapsed")

if 'font_size' not in st.session_state: st.session_state['font_size'] = '18px'

# --- 2. CSS CUSTOM (SUPPORT DARK MODE & GRID FIX) ---
st.markdown(f"""
<style>
    /* --- LOGIKA WARNA OTOMATIS (LIGHT/DARK) --- */
    :root {{
        --bg-color: #ffffff;
        --text-color: #333333;
        --card-bg: #ffffff;
        --border-color: #e0e0e0;
    }}

    @media (prefers-color-scheme: dark) {{
        :root {{
            --bg-color: #0e1117;
            --text-color: #fafafa;
            --card-bg: #262730;
            --border-color: #464b5f;
        }}
    }}

    /* Reset Header Bawaan */
    [data-testid="stHeader"] {{ display: none; }}
    
    /* Header Custom */
    .custom-header {{
        background: linear-gradient(90deg, #1e3a8a, #3b82f6);
        padding: 15px 20px; color: white; border-radius: 0 0 15px 15px;
        margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.2);
        display: flex; justify-content: space-between; align-items: center;
    }}
    
    /* Kotak Soal (Mengikuti Tema) */
    .soal-container {{
        background-color: var(--card-bg);
        color: var(--text-color);
        padding: 30px; 
        border-radius: 12px;
        border: 1px solid var(--border-color);
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        font-size: {st.session_state['font_size']}; 
        line-height: 1.8; 
        min-height: 450px;
    }}

    /* Legenda Status (Supaya Siswa Tahu Arti Warna) */
    .legend-box {{
        font-size: 12px; margin-bottom: 10px; display: flex; gap: 10px; flex-wrap: wrap;
    }}
    .legend-item {{ display: flex; align-items: center; gap: 5px; }}
    .dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
    
    /* Sembunyikan Elemen Mengganggu */
    footer {{ visibility: hidden; }}
    .stDeployButton {{ display: none; }}
    
    /* Perbaikan Tampilan Radio & Checkbox di Dark Mode */
    .stRadio label, .stCheckbox label {{ color: var(--text-color) !important; }}
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
if not db: st.error("Gagal koneksi database. Cek Secrets."); st.stop()

# --- 4. LOGIC SISTEM ---
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
    
    if doc.exists:
        data = doc.to_dict()
        if data.get('status') == 'completed': 
            st.warning("Ujian ini sudah selesai."); return False
        st.session_state.update({
            'exam_data': data, 'q_order': json.loads(data['q_order']),
            'answers': json.loads(data['answers']), 'ragu': json.loads(data.get('ragu', '[]')),
            'curr_idx': 0, 'exam_mode': True
        })
    else:
        q_ref = db.collection('questions').where('mapel', '==', mapel).where('paket', '==', paket).stream()
        q_list = [{'id': q.id, **q.to_dict()} for q in q_ref]
        if not q_list: st.error("Soal kosong."); return False
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

# --- 5. HALAMAN ---
def login_page():
    # Menggunakan container untuk layout login yang rapi
    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("<h1 style='text-align:center; color:#1e3a8a;'>🎓 CAT TKA SD</h1>", unsafe_allow_html=True)
        st.markdown("<div class='login-box'>", unsafe_allow_html=True)
        
        tab_in, tab_up = st.tabs(["🔑 Masuk", "📝 Daftar"])
        
        with tab_in:
            with st.form("login"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                if st.form_submit_button("Masuk", use_container_width=True):
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
                        if not found: st.error("Akun salah")
        
        with tab_up:
            with st.form("reg"):
                nu = st.text_input("Username Baru (Tanpa Spasi)")
                nn = st.text_input("Nama Lengkap")
                np = st.text_input("Password", type="password")
                if st.form_submit_button("Daftar", use_container_width=True):
                    if nu and nn and np:
                        chk = db.collection('users').document(nu).get()
                        if chk.exists: st.error("Username sudah dipakai.")
                        else:
                            db.collection('users').document(nu).set({'username':nu, 'password':np, 'nama_lengkap':nn, 'role':'siswa'})
                            st.success("Berhasil! Silakan Login.")
        
        st.markdown("</div>", unsafe_allow_html=True)

def admin_dashboard():
    st.markdown("<div class='custom-header'><h3>Dashboard Admin</h3><button onclick='window.location.href=\"/?logout=true\"' style='background:none;border:1px solid white;color:white;padding:5px 10px;border-radius:5px;cursor:pointer;'>Keluar</button></div>", unsafe_allow_html=True)
    if st.query_params.get("logout"): st.query_params.clear(); st.session_state.clear(); st.rerun()
    
    t1, t2, t3, t4 = st.tabs(["📝 Input Soal", "📂 Upload Teks (HP)", "🛠️ Edit Soal", "👥 Siswa"])
    
    with t1:
        st.subheader("Input Soal")
        cm, ct = st.columns(2)
        in_mapel = cm.selectbox("Mapel", ["Matematika", "Bahasa Indonesia"])
        in_tipe = ct.selectbox("Tipe", ["Pilihan Ganda (PG)", "PG Kompleks", "Benar/Salah"])
        in_paket = st.text_input("Paket", "Paket 1")
        
        with st.form("f_soal"):
            tanya = st.text_area("Pertanyaan")
            img = st.file_uploader("Gambar", type=['png','jpg'])
            opsi = []; kunci = None
            st.markdown("---")
            if in_tipe == "Pilihan Ganda (PG)":
                cols = st.columns(4)
                opsi = [cols[i].text_input(f"Opsi {chr(65+i)}") for i in range(4)]
                ans = st.radio("Kunci", ["A","B","C","D"], horizontal=True)
                if opsi[0]: kunci = opsi[ord(ans)-65]
                rt = 'single'
            elif in_tipe == "PG Kompleks":
                cols = st.columns(2); k_list = []
                for i in range(4):
                    v = cols[i%2].text_input(f"Pil {i+1}")
                    if v: opsi.append(v)
                    if cols[i%2].checkbox(f"Benar?", key=f"c{i}"): k_list.append(v)
                kunci = k_list; rt = 'complex'
            elif in_tipe == "Benar/Salah":
                kunci = {}
                for i in range(3):
                    c1, c2 = st.columns([3,1])
                    p = c1.text_input(f"Pernyataan {i+1}")
                    k = c2.radio(f"Kunci", ["Benar","Salah"], key=f"bs{i}", horizontal=True, label_visibility="collapsed")
                    if p: opsi.append(p); kunci[p] = k
                rt = 'category'
            
            if st.form_submit_button("Simpan"):
                imd = process_image(img)
                db.collection('questions').add({'mapel':in_mapel, 'paket':in_paket, 'tipe':rt, 'pertanyaan':tanya, 'gambar':imd, 'opsi':json.dumps(opsi), 'kunci_jawaban':json.dumps(kunci)})
                st.success("Disimpan!")

    with t2:
        st.subheader("Paste Teks CSV (Pemisah Pipa '|')")
        txt = st.text_area("Paste disini", height=200)
        if st.button("Proses"):
            try:
                df = pd.read_csv(io.StringIO(txt), sep='|')
                cnt = 0
                for _, r in df.iterrows():
                    olist = [str(r[c]) for c in ['pilihan_a','pilihan_b','pilihan_c','pilihan_d'] if pd.notna(r[c])]
                    rt='single'; rk=str(r['jawaban_benar']); fk=rk
                    if 'Check' in str(r['tipe']): rt='complex'; fk=[x.strip() for x in rk.split(',')]
                    elif 'Benar' in str(r['tipe']): 
                        rt='category'; ks=[x.strip() for x in rk.split(',')]
                        fk={olist[i]:ks[i] for i in range(len(ks)) if i<len(olist)}
                    db.collection('questions').add({'mapel':r['mapel'], 'paket':'Paket 1', 'tipe':rt, 'pertanyaan':r['pertanyaan'], 'gambar':None, 'opsi':json.dumps(olist), 'kunci_jawaban':json.dumps(fk)})
                    cnt+=1
                st.success(f"Masuk {cnt} Soal!")
            except Exception as e: st.error(f"Error: {e}")

    with t3:
        st.subheader("Edit Soal")
        fm = st.selectbox("Mapel", ["Matematika", "Bahasa Indonesia"], key="fm_ed")
        fp = st.text_input("Filter Paket", "Paket 1", key="fp_ed")
        qref = list(db.collection('questions').where('mapel','==',fm).where('paket','==',fp).stream())
        
        if qref:
            qs = [{'id':q.id, **q.to_dict()} for q in qref]
            sel = st.selectbox("Pilih Soal", range(len(qs)), format_func=lambda x: qs[x]['pertanyaan'][:60])
            q = qs[sel]
            with st.form("ed"):
                nt = st.text_area("Tanya", q['pertanyaan'])
                if q.get('gambar'): st.image(q['gambar'], width=200)
                ni = st.file_uploader("Ganti Gambar")
                if st.form_submit_button("Update"):
                    ud = {'pertanyaan':nt}
                    if ni: ud['gambar'] = process_image(ni)
                    db.collection('questions').document(q['id']).update(ud)
                    st.success("Updated!"); time.sleep(1); st.rerun()
            if st.button("Hapus Soal"):
                db.collection('questions').document(q['id']).delete(); st.rerun()

    with t4:
        st.subheader("Data Siswa")
        users = list(db.collection('users').where('role','!=','admin').stream())
        if users:
            udata = pd.DataFrame([u.to_dict() for u in users])
            st.dataframe(udata[['username','nama_lengkap']], hide_index=True)
            st.caption("Password disembunyikan untuk privasi.")

def student_dashboard():
    st.markdown(f"<div class='custom-header'><h3>Halo, {st.session_state['nama']}! 👋</h3><button onclick='window.location.href=\"/?logout=true\"' style='background:#ef4444; border:none; color:white; padding:8px 15px; border-radius:5px; cursor:pointer;'>Keluar</button></div>", unsafe_allow_html=True)
    if st.query_params.get("logout"): st.query_params.clear(); st.session_state.clear(); st.rerun()
    st.subheader("Pilih Ujian")
    if st.button("📐 Mulai Ujian Matematika (Paket 1)"):
        if init_exam("Matematika", "Paket 1"): st.rerun()

def exam_interface():
    data = st.session_state['exam_data']; order = st.session_state['q_order']; idx = st.session_state['curr_idx']
    rem = data['end_time'] - datetime.now().timestamp()
    if rem <= 0: finish_exam()
    
    # Header & Timer
    c1,c2,c3 = st.columns([6,2,2])
    with c1: st.markdown(f"**{data['mapel']}** | No. {idx+1}")
    with c2: st.markdown(f"<div style='background:#dbeafe; color:#1e40af; padding:5px; text-align:center; font-weight:bold; border-radius:5px;'>⏱️ {int(rem//60)}:{int(rem%60):02d}</div>", unsafe_allow_html=True)
    with c3: 
        c = st.columns(3)
        if c[0].button("A-"): st.session_state['font_size']='14px'; st.rerun()
        if c[1].button("A"): st.session_state['font_size']='18px'; st.rerun()
        if c[2].button("A+"): st.session_state['font_size']='24px'; st.rerun()
    
    col_soal, col_nav = st.columns([3, 1])
    
    with col_soal:
        qid = order[idx]
        q_doc = db.collection('questions').document(qid).get()
        if q_doc.exists:
            q = q_doc.to_dict()
            st.markdown(f"<div class='soal-container'>", unsafe_allow_html=True)
            st.write(q['pertanyaan'])
            if q.get('gambar'): st.image(q['gambar'])
            st.write("")
            
            opsi = json.loads(q['opsi']); ans = st.session_state['answers'].get(qid)
            if q['tipe'] == 'single':
                sel = st.radio("Jawab:", opsi, key=qid, index=opsi.index(ans) if ans in opsi else None)
                if sel: st.session_state['answers'][qid] = sel
            elif q['tipe'] == 'complex':
                st.write("Pilih > 1:"); sel = ans if isinstance(ans, list) else []; new_sel = []
                for o in opsi:
                    if st.checkbox(o, o in sel, key=f"{qid}_{o}"): new_sel.append(o)
                st.session_state['answers'][qid] = new_sel
            elif q['tipe'] == 'category':
                st.write("Benar/Salah:"); sel = ans if isinstance(ans, dict) else {}; new_sel = {}
                for o in opsi:
                    c_a, c_b = st.columns([3,1]); c_a.write(o)
                    v = c_b.radio(f"opt_{o}", ["Benar","Salah"], key=f"{qid}_{o}", horizontal=True, label_visibility="collapsed", index=0 if sel.get(o)=="Benar" else 1 if sel.get(o)=="Salah" else None)
                    if v: new_sel[o] = v
                st.session_state['answers'][qid] = new_sel
            st.markdown("</div>", unsafe_allow_html=True)

    with col_nav:
        st.write("**Navigasi Soal**")
        st.markdown("""
        <div class='legend-box'>
            <div class='legend-item'><span class='dot' style='background:#1e3a8a;'></span> Sudah</div>
            <div class='legend-item'><span class='dot' style='background:#facc15;'></span> Ragu</div>
            <div class='legend-item'><span class='dot' style='background:white; border:1px solid #ccc;'></span> Belum</div>
        </div>
        """, unsafe_allow_html=True)
        
        # GRID YANG SUDAH DIPERBAIKI (MENGGUNAKAN TOMBOL STANDAR DENGAN WARNA)
        cols = st.columns(5)
        for i, q_id in enumerate(order):
            # Tentukan Tipe Tombol
            btn_type = "secondary"
            label = str(i+1)
            
            # Cek status untuk memberi tanda visual di label
            if q_id == order[idx]:
                label = f"🔵 {i+1}" # Sedang dibuka
            elif q_id in st.session_state['ragu']:
                label = f"🟡 {i+1}" # Ragu
            elif q_id in st.session_state['answers'] and st.session_state['answers'][q_id]:
                label = f"✅ {i+1}" # Sudah dijawab
            
            if cols[i%5].button(label, key=f"nav_{i}", use_container_width=True):
                st.session_state['curr_idx'] = i; save_realtime(); st.rerun()

        st.divider()
        is_r = qid in st.session_state['ragu']
        if st.button(f"{'🟨 Batal Ragu' if is_r else '🟨 Ragu-Ragu'}", use_container_width=True):
            if is_r: st.session_state['ragu'].remove(qid)
            else: st.session_state['ragu'].append(qid)
            save_realtime(); st.rerun()
            
        c_p, c_n = st.columns(2)
        if idx > 0 and c_p.button("⬅️ Sblm", use_container_width=True):
            st.session_state['curr_idx']-=1; save_realtime(); st.rerun()
        if idx < len(order)-1: 
            if c_n.button("Lanjut ➡️", use_container_width=True):
                st.session_state['curr_idx']+=1; save_realtime(); st.rerun()
        else:
            if c_n.button("✅ Selesai", type="primary", use_container_width=True):
                finish_exam()

def finish_exam():
    save_realtime()
    sc, det = calculate_score()
    st.session_state.update({'exam_mode':False, 'result_mode':True, 'last_score':sc, 'last_det':det})
    st.rerun()

def result_interface():
    st.balloons(); st.markdown(f"<h1 style='text-align:center;'>Nilai Kamu: {st.session_state['last_score']:.1f}</h1>", unsafe_allow_html=True)
    if st.button("Kembali"): st.session_state['result_mode']=False; st.rerun()
    with st.expander("Detail"): st.json(st.session_state['last_det'])

# Main Loop
if not st.session_state.get('logged_in'): login_page()
else:
    if st.session_state['role'] == 'admin': admin_dashboard()
    else:
        if st.session_state.get('exam_mode'): exam_interface()
        elif st.session_state.get('result_mode'): result_interface()
        else: student_dashboard()
