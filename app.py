import streamlit as st
import pandas as pd
import time
import json
import base64
import io
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
        padding: 15px 20px; color: white; border-radius: 0 0 15px 15px;
        margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        display: flex; justify-content: space-between; align-items: center;
    }}
    .soal-container {{
        background: white; padding: 30px; border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        font-size: {st.session_state['font_size']}; line-height: 1.6; min-height: 450px;
    }}
    .nav-btn {{ width: 100%; font-weight: bold; border-radius: 4px; border: 1px solid #cbd5e1; background: white; }}
    .status-done {{ background-color: #4ade80 !important; color: white !important; border-color: #22c55e !important; }}
    .status-ragu {{ background-color: #facc15 !important; color: black !important; border-color: #eab308 !important; }}
    .status-current {{ border: 2px solid #2563eb !important; font-weight: bold !important; }}
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
    except Exception as e: return None

db = get_db()
if not db: st.error("Gagal koneksi database."); st.stop()

# --- 4. FUNGSI LOGIC ---
def process_image(uploaded_file):
    if uploaded_file is not None:
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
        if data.get('status') == 'completed': return False
        st.session_state.update({
            'exam_data': data, 'q_order': json.loads(data['q_order']),
            'answers': json.loads(data['answers']), 'ragu': json.loads(data.get('ragu', '[]')),
            'curr_idx': 0, 'exam_mode': True
        })
    else:
        q_ref = db.collection('questions').where('mapel', '==', mapel).where('paket', '==', paket).stream()
        q_list = [{'id': q.id, **q.to_dict()} for q in q_ref]
        if not q_list: st.error("Soal kosong."); return False
            
        import random
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

def finish_exam():
    save_realtime()
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
    st.session_state.update({'exam_mode': False, 'result_mode': True, 'last_score': final, 'last_det': details})
    st.rerun()

# --- 5. HALAMAN UTAMA ---
def main():
    if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
    if not st.session_state['logged_in']: login_page()
    else:
        if st.session_state['role'] == 'admin': admin_dashboard()
        else:
            if st.session_state.get('exam_mode'): exam_interface()
            elif st.session_state.get('result_mode'): result_interface()
            else: student_dashboard()

def login_page():
    st.markdown("<br><br><h1 style='text-align:center; color:#1e3a8a;'>🎓 CAT TKA SD</h1>", unsafe_allow_html=True)
    c1,c2,c3 = st.columns([1,2,1])
    with c2:
        with st.form("login"):
            u = st.text_input("Username"); p = st.text_input("Password", type="password")
            if st.form_submit_button("Masuk", use_container_width=True):
                if u=="admin" and p=="admin123":
                    st.session_state.update({'logged_in':True, 'role':'admin', 'nama':'Administrator', 'username':'admin'})
                    st.rerun()
                else:
                    users = db.collection('users').where('username','==',u).where('password','==',p).stream()
                    for user in users:
                        d = user.to_dict()
                        st.session_state.update({'logged_in':True, 'role':'siswa', 'nama':d['nama_lengkap'], 'username':d['username']})
                        st.rerun()
                    st.error("Gagal Login")

def admin_dashboard():
    st.markdown("<div class='custom-header'><h3>Dashboard Admin</h3><button onclick='window.location.reload()'>Keluar</button></div>", unsafe_allow_html=True)
    if st.button("Keluar"): st.session_state.clear(); st.rerun()
    
    # MENU TAB ADMIN
    tab1, tab2, tab3, tab4 = st.tabs(["📝 Input Soal", "📂 Upload Massal (HP)", "🛠️ Edit Soal", "👥 Siswa"])
    
    # --- TAB 1: INPUT SOAL MANUAL ---
    with tab1:
        st.subheader("Input Satu Soal")
        c_m, c_t = st.columns(2)
        in_mapel = c_m.selectbox("Mapel", ["Matematika", "Bahasa Indonesia"])
        in_tipe = c_t.selectbox("Tipe", ["Pilihan Ganda (PG)", "PG Kompleks", "Benar/Salah"])
        in_paket = st.text_input("Paket", "Paket 1")
        
        with st.form("add_soal"):
            tanya = st.text_area("Pertanyaan")
            img = st.file_uploader("Gambar (Opsional)", type=['png','jpg','jpeg'])
            
            opsi = []; kunci = None
            st.markdown("---")
            
            if in_tipe == "Pilihan Ganda (PG)":
                cols = st.columns(4)
                opsi = [cols[i].text_input(f"Opsi {chr(65+i)}") for i in range(4)]
                ans = st.radio("Kunci", ["A","B","C","D"], horizontal=True)
                if opsi[0]: kunci = opsi[ord(ans)-65]
                real_tipe = 'single'
                
            elif in_tipe == "PG Kompleks":
                cols = st.columns(2); kunci_list = []
                for i in range(4):
                    val = cols[i%2].text_input(f"Pilihan {i+1}")
                    if val: opsi.append(val)
                    if cols[i%2].checkbox(f"Benar?", key=f"c_{i}"): kunci_list.append(val)
                kunci = kunci_list; real_tipe = 'complex'
                
            elif in_tipe == "Benar/Salah":
                kunci = {}
                for i in range(3):
                    c1, c2 = st.columns([3,1])
                    p = c1.text_input(f"Pernyataan {i+1}")
                    k = c2.radio(f"Kunci {i+1}", ["Benar","Salah"], horizontal=True, key=f"bs_{i}")
                    if p: opsi.append(p); kunci[p] = k
                real_tipe = 'category'
            
            if st.form_submit_button("Simpan"):
                img_d = process_image(img)
                db.collection('questions').add({
                    'mapel':in_mapel, 'paket':in_paket, 'tipe':real_tipe, 'pertanyaan':tanya, 'gambar':img_d,
                    'opsi':json.dumps(opsi), 'kunci_jawaban':json.dumps(kunci)
                })
                st.success("Tersimpan!")

    # --- TAB 2: UPLOAD (KHUSUS HP) ---
    with tab2:
        st.subheader("Upload Soal Cepat (Copy-Paste)")
        st.info("Copy teks CSV dari Chatbot, lalu Paste di bawah ini. Tidak perlu file!")
        
        csv_text = st.text_area("Paste Teks CSV Di Sini", height=200)
        if st.button("Proses Teks CSV"):
            try:
                df = pd.read_csv(io.StringIO(csv_text))
                count = 0
                for _, row in df.iterrows():
                    o_list = [str(row[c]) for c in ['pilihan_a','pilihan_b','pilihan_c','pilihan_d'] if pd.notna(row[c])]
                    rt = 'single'; raw_k = str(row['jawaban_benar']); fk = raw_k
                    if 'Check' in str(row['tipe']): rt='complex'; fk=[x.strip() for x in raw_k.split(',')]
                    elif 'Benar' in str(row['tipe']): 
                        rt='category'; ks=[x.strip() for x in raw_k.split(',')]
                        fk = {o_list[i]: ks[i] for i in range(len(ks)) if i < len(o_list)}
                    
                    db.collection('questions').add({
                        'mapel': row['mapel'], 'paket': 'Paket 1', 'tipe': rt,
                        'pertanyaan': row['pertanyaan'], 'gambar': None,
                        'opsi': json.dumps(o_list), 'kunci_jawaban': json.dumps(fk)
                    })
                    count += 1
                st.success(f"Berhasil: {count} Soal Masuk!")
            except Exception as e: st.error(f"Format Salah: {e}")

    # --- TAB 3: EDIT SOAL (FITUR BARU) ---
    with tab3:
        st.subheader("Edit / Hapus Soal")
        f_mapel = st.selectbox("Filter Mapel", ["Matematika", "Bahasa Indonesia"], key="f_mapel")
        f_paket = st.text_input("Filter Paket", "Paket 1", key="f_paket")
        
        q_ref = db.collection('questions').where('mapel','==',f_mapel).where('paket','==',f_paket).stream()
        q_list = [{'id': q.id, **q.to_dict()} for q in q_ref]
        
        if q_list:
            q_titles = [f"{q['pertanyaan'][:50]}..." for q in q_list]
            sel_idx = st.selectbox("Pilih Soal", range(len(q_list)), format_func=lambda x: q_titles[x])
            q_sel = q_list[sel_idx]
            
            st.markdown("---")
            with st.form("edit_soal_form"):
                st.caption(f"ID: {q_sel['id']}")
                ed_tanya = st.text_area("Pertanyaan", q_sel['pertanyaan'])
                if q_sel.get('gambar'): st.image(q_sel['gambar'], width=200, caption="Gambar Lama")
                ed_img = st.file_uploader("Ganti Gambar", type=['png','jpg'])
                
                st.warning("Edit Opsi & Kunci (Hati-hati, format Text/JSON)")
                ed_opsi = st.text_area("Opsi", q_sel['opsi'])
                ed_kunci = st.text_area("Kunci", q_sel['kunci_jawaban'])
                
                c_up, c_del = st.columns(2)
                do_update = c_up.form_submit_button("💾 Simpan Perubahan")
                do_del = c_del.form_submit_button("🗑️ Hapus Soal", type="primary")
                
                if do_update:
                    update_data = {'pertanyaan': ed_tanya, 'opsi': ed_opsi, 'kunci_jawaban': ed_kunci}
                    if ed_img: update_data['gambar'] = process_image(ed_img)
                    db.collection('questions').document(q_sel['id']).update(update_data)
                    st.success("Terupdate!"); time.sleep(1); st.rerun()
                if do_del:
                    db.collection('questions').document(q_sel['id']).delete()
                    st.warning("Terhapus!"); time.sleep(1); st.rerun()
        else: st.info("Tidak ada soal.")

    # --- TAB 4: SISWA ---
    with tab4:
        st.subheader("Data Siswa")
        users = list(db.collection('users').where('role','!=','admin').stream())
        if users:
            ulist = pd.DataFrame([u.to_dict() for u in users])
            st.dataframe(ulist)
            
            st.write("### Tambah/Edit Akun")
            with st.form("user_mng"):
                edit_u = st.text_input("Username (Isi username lama untuk edit)")
                edit_p = st.text_input("Password Baru")
                edit_n = st.text_input("Nama Lengkap Baru")
                
                c1, c2 = st.columns(2)
                if c1.form_submit_button("Simpan/Update"):
                    db.collection('users').document(edit_u).set({'username':edit_u, 'password':edit_p, 'nama_lengkap':edit_n, 'role':'siswa'})
                    st.success("Tersimpan!"); st.rerun()
                if c2.form_submit_button("Hapus Akun", type="primary"):
                    db.collection('users').document(edit_u).delete(); st.warning("Terhapus!"); st.rerun()

def student_dashboard():
    st.markdown(f"<div class='custom-header'><h3>Halo, {st.session_state['nama']}</h3><button onclick='window.location.reload()'>Keluar</button></div>", unsafe_allow_html=True)
    if st.sidebar.button("Keluar"): st.session_state.clear(); st.rerun()
    st.subheader("Pilih Ujian")
    if st.button("📐 Mulai Ujian Matematika (Paket 1)"):
        if init_exam("Matematika", "Paket 1"): st.rerun()

def exam_interface():
    data = st.session_state['exam_data']; order = st.session_state['q_order']; idx = st.session_state['curr_idx']
    rem = data['end_time'] - datetime.now().timestamp()
    if rem <= 0: finish_exam()
    mins, secs = divmod(int(rem), 60)
    
    c1,c2,c3 = st.columns([6,2,2])
    with c1: st.markdown(f"**{data['mapel']}** | No. {idx+1}")
    with c2: st.markdown(f"<div style='background:#dbeafe; color:#1e40af; padding:5px; text-align:center;'>⏱️ {mins:02d}:{secs:02d}</div>", unsafe_allow_html=True)
    with c3: 
        c = st.columns(3)
        if c[0].button("A-"): st.session_state['font_size']='14px'; st.rerun()
        if c[1].button("A"): st.session_state['font_size']='18px'; st.rerun()
        if c[2].button("A+"): st.session_state['font_size']='24px'; st.rerun()
    st.divider()
    
    col_soal, col_nav = st.columns([3,1])
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
        st.write("Navigasi")
        cols = st.columns(5)
        for i, q_id in enumerate(order):
            s = "status-done" if q_id in st.session_state['answers'] and st.session_state['answers'][q_id] else ""
            if q_id in st.session_state['ragu']: s = "status-ragu"
            if i == idx: s += " status-current"
            if cols[i%5].button(f"{i+1}", key=f"n{i}"): st.session_state['curr_idx']=i; save_realtime(); st.rerun()
        
        st.markdown("---")
        is_r = qid in st.session_state['ragu']
        if st.button(f"{'🟨 Batal Ragu' if is_r else '🟨 Ragu'}", use_container_width=True):
            if is_r: st.session_state['ragu'].remove(qid)
            else: st.session_state['ragu'].append(qid)
            save_realtime(); st.rerun()
        c_p, c_n = st.columns(2)
        if idx > 0 and c_p.button("⬅️ Prev"): st.session_state['curr_idx']-=1; save_realtime(); st.rerun()
        if idx < len(order)-1: 
            if c_n.button("Next ➡️"): st.session_state['curr_idx']+=1; save_realtime(); st.rerun()
        else:
            if c_n.button("✅ Selesai", type="primary"): finish_exam()

def result_interface():
    st.balloons(); st.success(f"Nilai: {st.session_state['last_score']:.1f}")
    if st.button("Kembali"): st.session_state['result_mode']=False; st.rerun()
    with st.expander("Detail"): st.json(st.session_state['last_det'])

if __name__ == "__main__": main()
