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

# --- 2. CSS CUSTOM ---
st.markdown(f"""
<style>
    [data-testid="stAppViewContainer"] {{ background-color: #f0f3f5; color: #333; }}
    [data-testid="stHeader"] {{ display: none; }}
    .custom-header {{
        background: linear-gradient(90deg, #1e3a8a, #3b82f6);
        padding: 20px; color: white; border-radius: 0 0 20px 20px;
        margin-bottom: 30px; box-shadow: 0 4px 10px rgba(0,0,0,0.1);
        display: flex; justify-content: space-between; align-items: center;
    }}
    .soal-container {{
        background: white; padding: 40px; border-radius: 15px;
        box-shadow: 0 5px 15px rgba(0,0,0,0.05);
        font-size: {st.session_state['font_size']}; line-height: 1.8; min-height: 500px;
    }}
    .grid-btn {{
        width: 100%; aspect-ratio: 1; border: 1px solid #ccc; border-radius: 8px;
        font-weight: bold; display: flex; align-items: center; justify-content: center;
        margin-bottom: 8px; cursor: pointer; font-size: 14px; background: white;
        transition: all 0.2s;
    }}
    .grid-btn:hover {{ transform: scale(1.05); }}
    .status-done {{ background-color: #1e3a8a !important; color: white !important; border-color: #1e3a8a !important; }}
    .status-ragu {{ background-color: #facc15 !important; color: black !important; border-color: #eab308 !important; }}
    .status-current {{ border: 2px solid #3b82f6 !important; font-weight: 900 !important; transform: scale(1.1); box-shadow: 0 0 10px rgba(59,130,246,0.5); }}
    
    /* Login Box */
    .login-box {{
        background: white; padding: 30px; border-radius: 15px;
        box-shadow: 0 10px 25px rgba(0,0,0,0.1);
        margin-top: 50px;
    }}
    
    footer {{ visibility: hidden; }}
    .stDeployButton {{ display: none; }}
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
if not db: st.error("Gagal koneksi database."); st.stop()

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
            st.warning("Kamu sudah menyelesaikan ujian ini. Nilai sudah tersimpan."); return False
        st.session_state.update({
            'exam_data': data, 'q_order': json.loads(data['q_order']),
            'answers': json.loads(data['answers']), 'ragu': json.loads(data.get('ragu', '[]')),
            'curr_idx': 0, 'exam_mode': True
        })
    else:
        q_ref = db.collection('questions').where('mapel', '==', mapel).where('paket', '==', paket).stream()
        q_list = [{'id': q.id, **q.to_dict()} for q in q_ref]
        if not q_list: st.error("Soal belum tersedia, hubungi Guru."); return False
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
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("<br><br><h1 style='text-align:center; color:#1e3a8a;'>🎓 CAT TKA SD</h1>", unsafe_allow_html=True)
        
        # TAB UNTUK MASUK / DAFTAR
        tab_login, tab_daftar = st.tabs(["🔑 Masuk", "📝 Daftar Akun Baru"])
        
        with tab_login:
            with st.form("login_form"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                if st.form_submit_button("Masuk", use_container_width=True):
                    if u=="admin" and p=="admin123":
                        st.session_state.update({'logged_in':True, 'role':'admin', 'nama':'Administrator', 'username':'admin'})
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
                        if not found: st.error("Username atau Password salah")

        with tab_daftar:
            st.info("Belum punya akun? Buat sendiri di sini.")
            with st.form("register_form"):
                new_u = st.text_input("Buat Username (Tanpa spasi)", placeholder="contoh: budi123")
                new_n = st.text_input("Nama Lengkap", placeholder="Budi Santoso")
                new_p = st.text_input("Buat Password", type="password")
                
                if st.form_submit_button("Daftar Sekarang", use_container_width=True):
                    if new_u and new_n and new_p:
                        # Cek username kembar
                        check = db.collection('users').document(new_u).get()
                        if check.exists:
                            st.error("Username sudah dipakai teman lain. Coba yang lain.")
                        else:
                            db.collection('users').document(new_u).set({
                                'username': new_u, 'password': new_p, 
                                'nama_lengkap': new_n, 'role': 'siswa'
                            })
                            st.success("Berhasil daftar! Silakan pindah ke tab 'Masuk'.")
                    else:
                        st.warning("Semua kolom harus diisi ya.")

def admin_dashboard():
    st.markdown("<div class='custom-header'><h3>Dashboard Admin</h3><button onclick='window.location.href=\"/?logout=true\"' style='background:none;border:1px solid white;color:white;padding:5px 10px;border-radius:5px;cursor:pointer;'>Keluar</button></div>", unsafe_allow_html=True)
    if st.query_params.get("logout"): st.query_params.clear(); st.session_state.clear(); st.rerun()
    
    t1, t2, t3, t4 = st.tabs(["📝 Input Soal", "📂 Upload Teks (HP)", "🛠️ Edit Soal", "👥 Data Siswa"])
    
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
        st.subheader("Paste Teks CSV (Pemisah Garis Tegak '|')")
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

    # --- TAB 4: DATA SISWA (HANYA VIEW, NO PASSWORD) ---
    with t4:
        st.subheader("Daftar Siswa Terdaftar")
        users = list(db.collection('users').where('role','!=','admin').stream())
        if users:
            # Hanya tampilkan Username dan Nama, Password disembunyikan
            data_view = [{"Username": u.to_dict().get('username'), "Nama Lengkap": u.to_dict().get('nama_lengkap')} for u in users]
            st.dataframe(pd.DataFrame(data_view), use_container_width=True)
            
            st.caption(f"Total Siswa: {len(users)}")
            
            with st.expander("Kelola Akun (Hapus/Reset)"):
                st.warning("Area Berbahaya: Hapus akun jika ada siswa lupa password atau salah input.")
                pilih_hapus = st.selectbox("Pilih Username untuk Dihapus", [u['Username'] for u in data_view])
                if st.button("Hapus Akun Siswa Ini", type="primary"):
                    db.collection('users').document(pilih_hapus).delete()
                    st.success("Terhapus"); time.sleep(1); st.rerun()

def student_dashboard():
    # HEADER DENGAN SAPAAN
    st.markdown(f"""
    <div class='custom-header'>
        <div>
            <h2 style='margin:0;'>Haloo {st.session_state['nama']}! 👋</h2>
            <p style='margin:0; opacity:0.9;'>Siap untuk latihan hari ini?</p>
        </div>
        <button onclick='window.location.href=\"/?logout=true\"' style='background:#ef4444; border:none; color:white; padding:8px 15px; border-radius:5px; cursor:pointer; font-weight:bold;'>Keluar</button>
    </div>
    """, unsafe_allow_html=True)
    
    if st.query_params.get("logout"): st.query_params.clear(); st.session_state.clear(); st.rerun()
    
    col_main, _ = st.columns([2, 1])
    with col_main:
        st.subheader("Pilih Mata Pelajaran")
        c1, c2 = st.columns(2)
        with c1:
            with st.container(border=True):
                st.markdown("### 📐 Matematika")
                st.write("30 Soal | 75 Menit")
                if st.button("Mulai Paket 1", key="btn_mtk", type="primary", use_container_width=True):
                    if init_exam("Matematika", "Paket 1"): st.rerun()
        with c2:
            with st.container(border=True):
                st.markdown("### 📖 B. Indonesia")
                st.write("Segera Hadir")
                st.button("Belum Tersedia", disabled=True, use_container_width=True)

def exam_interface():
    data = st.session_state['exam_data']; order = st.session_state['q_order']; idx = st.session_state['curr_idx']
    rem = data['end_time'] - datetime.now().timestamp()
    if rem <= 0: finish_exam()
    
    c1,c2,c3 = st.columns([6,2,2])
    with c1: st.markdown(f"**{data['mapel']}** | No. {idx+1}")
    with c2: st.markdown(f"<div style='background:#dbeafe; color:#1e40af; padding:5px; text-align:center;'>⏱️ {int(rem//60)}:{int(rem%60):02d}</div>", unsafe_allow_html=True)
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
        with st.expander("Daftar Soal", expanded=True):
            cols = st.columns(5)
            for i, q_id in enumerate(order):
                bg = "white"; border = "#ccc"; txt = "black"
                if q_id in st.session_state['answers'] and st.session_state['answers'][q_id]:
                    bg = "#1e3a8a"; txt = "white"
                if q_id in st.session_state['ragu']:
                    bg = "#facc15"; txt = "black"
                if i == idx:
                    border = "#3b82f6"
                cols[i%5].markdown(f"""<div style="background:{bg}; color:{txt}; border:2px solid {border}; border-radius:5px; text-align:center; padding:5px; cursor:default; font-weight:bold;">{i+1}</div>""", unsafe_allow_html=True)
                if cols[i%5].button(f"Go {i+1}", key=f"n{i}", label_visibility="collapsed"):
                    st.session_state['curr_idx'] = i; save_realtime(); st.rerun()

        st.divider()
        is_r = qid in st.session_state['ragu']
        if st.button(f"{'🟨 Batal Ragu' if is_r else '🟨 Ragu'}", use_container_width=True):
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
