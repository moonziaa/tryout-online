import streamlit as st
import pandas as pd
import time
import json
import base64
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
            'exam_data': data,
            'q_order': json.loads(data['q_order']),
            'answers': json.loads(data['answers']),
            'ragu': json.loads(data.get('ragu', '[]')),
            'curr_idx': 0
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
            'exam_data': new_data, 'q_order': q_order, 'answers': {}, 'ragu': [], 'curr_idx': 0
        })
    st.session_state['exam_mode'] = True
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
            if 'exam_mode' in st.session_state and st.session_state['exam_mode']: exam_interface()
            elif 'result_mode' in st.session_state and st.session_state['result_mode']: result_interface()
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
                    found = False
                    for user in users:
                        d = user.to_dict()
                        st.session_state.update({'logged_in':True, 'role':'siswa', 'nama':d['nama_lengkap'], 'username':d['username']})
                        found = True; st.rerun()
                    if not found: st.error("Akun tidak ditemukan")

def admin_dashboard():
    st.markdown("<div class='custom-header'><h3>Dashboard Admin</h3><button onclick='window.location.reload()'>Keluar</button></div>", unsafe_allow_html=True)
    if st.button("Keluar"): st.session_state.clear(); st.rerun()
    
    tab1, tab2, tab3 = st.tabs(["👥 Manajemen Siswa", "📝 Input Soal", "📊 Rekap Nilai"])
    
    # --- TAB 1: SISWA (EDIT/HAPUS DIKEMBALIKAN) ---
    with tab1:
        st.subheader("Daftar Siswa")
        users = list(db.collection('users').where('role','!=','admin').stream())
        
        if users:
            # Tampilkan Tabel
            user_list = [{"Username": u.id, "Nama": u.to_dict().get('nama_lengkap'), "Password": u.to_dict().get('password')} for u in users]
            st.dataframe(pd.DataFrame(user_list))
            
            st.divider()
            st.write("### Edit / Hapus Siswa")
            
            # Pilih Siswa untuk diedit
            pilihan_siswa = st.selectbox("Pilih Akun untuk Diedit:", [u['Username'] for u in user_list])
            
            # Cari data siswa terpilih
            selected_data = next((item for item in user_list if item["Username"] == pilihan_siswa), None)
            
            if selected_data:
                with st.form("edit_user"):
                    new_name = st.text_input("Nama Lengkap", value=selected_data['Nama'])
                    new_pass = st.text_input("Password", value=selected_data['Password'])
                    
                    c_edit, c_del = st.columns(2)
                    update = c_edit.form_submit_button("💾 Simpan Perubahan")
                    delete = c_del.form_submit_button("🗑️ Hapus Akun", type="primary")
                    
                    if update:
                        db.collection('users').document(pilihan_siswa).update({
                            'nama_lengkap': new_name, 'password': new_pass
                        })
                        st.success("Data berhasil diupdate!"); time.sleep(1); st.rerun()
                        
                    if delete:
                        db.collection('users').document(pilihan_siswa).delete()
                        st.warning("Akun dihapus!"); time.sleep(1); st.rerun()

        st.divider()
        with st.expander("➕ Tambah Siswa Baru"):
            with st.form("add_new"):
                nu = st.text_input("Username Baru"); np = st.text_input("Password"); nn = st.text_input("Nama Lengkap")
                if st.form_submit_button("Buat Akun"):
                    db.collection('users').document(nu).set({'username':nu, 'password':np, 'nama_lengkap':nn, 'role':'siswa'})
                    st.success("Siswa ditambahkan"); st.rerun()

    # --- TAB 2: INPUT SOAL (PERBAIKAN LOGIC) ---
    with tab2:
        st.subheader("Input Soal")
        
        # 1. PILIH TIPE DI LUAR FORM (Supaya UI Berubah Realtime)
        col_set_a, col_set_b = st.columns(2)
        in_mapel = col_set_a.selectbox("Mapel", ["Matematika", "Bahasa Indonesia"])
        in_tipe = col_set_b.selectbox("Tipe Soal", ["Pilihan Ganda (PG)", "PG Kompleks", "Benar/Salah"])
        in_paket = st.text_input("Nama Paket", "Paket 1")
        
        # 2. ISI FORM SESUAI TIPE
        with st.form("form_soal"):
            in_tanya = st.text_area("Pertanyaan")
            in_img = st.file_uploader("Gambar (Opsional)", type=['png','jpg','jpeg'])
            
            opsi = []; kunci = None
            st.markdown("---")
            
            # LOGIC UI DINAMIS
            if in_tipe == "Pilihan Ganda (PG)":
                cols = st.columns(4)
                opsi = [cols[i].text_input(f"Opsi {chr(65+i)}") for i in range(4)]
                ans = st.radio("Kunci Jawaban", ["A", "B", "C", "D"], horizontal=True)
                if opsi[0]: kunci = opsi[ord(ans)-65]
                real_tipe = 'single'
                
            elif in_tipe == "PG Kompleks":
                st.info("Centang semua jawaban yang benar.")
                cols = st.columns(2)
                kunci_list = []
                for i in range(4): # 4 Opsi Checkbox
                    val = cols[i%2].text_input(f"Pilihan {i+1}")
                    if val: opsi.append(val)
                    if cols[i%2].checkbox(f"Benar?", key=f"chk_in_{i}"): kunci_list.append(val)
                kunci = kunci_list
                real_tipe = 'complex'
                
            elif in_tipe == "Benar/Salah":
                st.info("Masukkan pernyataan dan tentukan kuncinya.")
                # Pernyataan 1
                c1a, c1b = st.columns([3,1])
                p1 = c1a.text_input("Pernyataan 1")
                k1 = c1b.radio("Kunci 1", ["Benar","Salah"], horizontal=True, key="k1_in")
                # Pernyataan 2
                c2a, c2b = st.columns([3,1])
                p2 = c2a.text_input("Pernyataan 2")
                k2 = c2b.radio("Kunci 2", ["Benar","Salah"], horizontal=True, key="k2_in")
                # Pernyataan 3
                c3a, c3b = st.columns([3,1])
                p3 = c3a.text_input("Pernyataan 3 (Opsional)")
                k3 = c3b.radio("Kunci 3", ["Benar","Salah"], horizontal=True, key="k3_in")
                
                opsi = [p for p in [p1, p2, p3] if p]
                kunci = {p1: k1, p2: k2}
                if p3: kunci[p3] = k3
                real_tipe = 'category'
            
            if st.form_submit_button("Simpan Soal"):
                img_data = process_image(in_img)
                db.collection('questions').add({
                    'mapel': in_mapel, 'paket': in_paket, 'tipe': real_tipe,
                    'pertanyaan': in_tanya, 'gambar': img_data,
                    'opsi': json.dumps(opsi), 'kunci_jawaban': json.dumps(kunci)
                })
                st.success("Soal Tersimpan!")

        # Upload CSV (Backup)
        with st.expander("Upload CSV Massal"):
            up = st.file_uploader("File CSV", type=['csv'])
            if up and st.button("Proses CSV"):
                try:
                    df = pd.read_csv(up)
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
                    st.success("Upload Sukses!")
                except: st.error("Format CSV Salah")

    with tab3:
        st.subheader("Rekap Nilai")
        if st.button("Refresh"): st.rerun()
        res = list(db.collection('results').order_by('tanggal', direction=firestore.Query.DESCENDING).stream())
        if res:
            df = pd.DataFrame([r.to_dict() for r in res])
            st.dataframe(df)

def student_dashboard():
    st.markdown(f"<div class='custom-header'><h3>Halo, {st.session_state['nama']}</h3><button onclick='window.location.reload()'>Keluar</button></div>", unsafe_allow_html=True)
    if st.sidebar.button("Keluar"): st.session_state.clear(); st.rerun()
    st.subheader("Pilih Ujian")
    c1, c2 = st.columns(2)
    with c1:
        st.info("📐 **Matematika**")
        if st.button("Mulai Paket 1"):
            if init_exam("Matematika", "Paket 1"): st.rerun()
    with c2: st.success("📖 **B. Indonesia**"); st.write("(Belum ada)")

def exam_interface():
    data = st.session_state['exam_data']; order = st.session_state['q_order']; idx = st.session_state['curr_idx']
    rem = data['end_time'] - datetime.now().timestamp()
    if rem <= 0: finish_exam()
    mins, secs = divmod(int(rem), 60)
    
    col_h1, col_h2, col_h3 = st.columns([6, 2, 2])
    with col_h1: st.markdown(f"**{data['mapel']}** | No. {idx+1}")
    with col_h2: st.markdown(f"<div style='background:#dbeafe; color:#1e40af; padding:5px; border-radius:5px; text-align:center;'>⏱️ {mins:02d}:{secs:02d}</div>", unsafe_allow_html=True)
    with col_h3: 
        fs = st.columns(3)
        if fs[0].button("A-"): st.session_state['font_size']='14px'; st.rerun()
        if fs[1].button("A"): st.session_state['font_size']='18px'; st.rerun()
        if fs[2].button("A+"): st.session_state['font_size']='24px'; st.rerun()
    st.divider()
    
    c_soal, c_nav = st.columns([3, 1])
    with c_soal:
        qid = order[idx]
        q_doc = db.collection('questions').document(qid).get()
        if q_doc.exists:
            q = q_doc.to_dict()
            st.markdown(f"<div class='soal-container'>", unsafe_allow_html=True)
            st.write(q['pertanyaan'])
            if q.get('gambar'): st.image(q['gambar'], use_column_width=True)
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

    with c_nav:
        st.write("Navigasi")
        cols = st.columns(5)
        for i, q_id in enumerate(order):
            style = "status-done" if q_id in st.session_state['answers'] and st.session_state['answers'][q_id] else ""
            if q_id in st.session_state['ragu']: style = "status-ragu"
            if i == idx: style += " status-current"
            if cols[i%5].button(f"{i+1}", key=f"nav_{i}"): st.session_state['curr_idx']=i; save_realtime(); st.rerun()
        
        st.markdown("---")
        is_ragu = qid in st.session_state['ragu']
        if st.button(f"{'🟨 Batal Ragu' if is_ragu else '🟨 Ragu-Ragu'}", use_container_width=True):
            if is_ragu: st.session_state['ragu'].remove(qid)
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
