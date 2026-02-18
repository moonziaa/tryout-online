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

# --- 2. CSS CUSTOM (TAMPILAN ANBK/PUSMENDIK) ---
st.markdown(f"""
<style>
    /* Reset Tampilan Streamlit */
    [data-testid="stAppViewContainer"] {{ background-color: #f0f3f5; color: #333; }}
    [data-testid="stHeader"] {{ display: none; }}
    
    /* Header Biru ala Pusmendik */
    .custom-header {{
        background: linear-gradient(90deg, #1e3a8a, #3b82f6);
        padding: 15px 20px; color: white; border-radius: 0 0 15px 15px;
        margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        display: flex; justify-content: space-between; align-items: center;
    }}
    
    /* Kotak Soal */
    .soal-container {{
        background: white; padding: 30px; border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        font-size: {st.session_state['font_size']}; line-height: 1.6; min-height: 450px;
    }}
    
    /* Navigasi Nomor */
    .nav-btn {{ width: 100%; font-weight: bold; border-radius: 4px; border: 1px solid #cbd5e1; background: white; }}
    .status-done {{ background-color: #4ade80 !important; color: white !important; border-color: #22c55e !important; }}
    .status-ragu {{ background-color: #facc15 !important; color: black !important; border-color: #eab308 !important; }}
    .status-current {{ border: 2px solid #2563eb !important; font-weight: bold !important; }}
    
    /* Sembunyikan Elemen Mengganggu */
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
    except Exception as e:
        return None

db = get_db()
if not db:
    st.error("Gagal koneksi database. Pastikan 'Secrets' di Streamlit sudah diisi dengan benar.")
    st.stop()

# --- 4. FUNGSI LOGIC ---
def process_image(uploaded_file):
    """Convert gambar upload ke Base64 string agar bisa disimpan di Firestore"""
    if uploaded_file is not None:
        bytes_data = uploaded_file.getvalue()
        base64_str = base64.b64encode(bytes_data).decode()
        return f"data:image/png;base64,{base64_str}"
    return None

def init_exam(mapel, paket):
    """Mulai sesi ujian baru / resume"""
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
        # Ambil soal dari DB
        q_ref = db.collection('questions').where('mapel', '==', mapel).where('paket', '==', paket).stream()
        q_list = [{'id': q.id, **q.to_dict()} for q in q_ref]
        
        if not q_list:
            st.error("Soal belum tersedia untuk paket ini."); return False
            
        import random
        random.shuffle(q_list) # Acak soal
        q_order = [q['id'] for q in q_list]
        
        start_ts = datetime.now().timestamp()
        new_data = {
            'username': st.session_state['username'], 'mapel': mapel, 'paket': paket,
            'start_time': start_ts, 'end_time': start_ts + (75*60), # 75 menit
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
    """Auto-save jawaban ke DB"""
    sid = f"{st.session_state['username']}_{st.session_state['exam_data']['mapel']}_{st.session_state['exam_data']['paket']}"
    db.collection('exam_sessions').document(sid).update({
        'answers': json.dumps(st.session_state['answers']),
        'ragu': json.dumps(st.session_state['ragu'])
    })

def finish_exam():
    save_realtime()
    q_ids = st.session_state['q_order']
    ans = st.session_state['answers']
    score = 0
    details = []
    
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
    
    # Update status
    sid = f"{st.session_state['username']}_{st.session_state['exam_data']['mapel']}_{st.session_state['exam_data']['paket']}"
    db.collection('exam_sessions').document(sid).update({'status': 'completed', 'score': final})
    
    # Simpan ke history
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

    if not st.session_state['logged_in']:
        login_page()
    else:
        if st.session_state['role'] == 'admin':
            admin_dashboard()
        else:
            if 'exam_mode' in st.session_state and st.session_state['exam_mode']:
                exam_interface()
            elif 'result_mode' in st.session_state and st.session_state['result_mode']:
                result_interface()
            else:
                student_dashboard()

def login_page():
    st.markdown("<br><br><h1 style='text-align:center; color:#1e3a8a;'>🎓 CAT TKA SD</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        with st.form("login"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            if st.form_submit_button("Masuk", use_container_width=True):
                if u == "admin" and p == "admin123":
                    st.session_state.update({'logged_in':True, 'role':'admin', 'nama':'Administrator', 'username':'admin'})
                    st.rerun()
                else:
                    users = db.collection('users').where('username', '==', u).where('password', '==', p).stream()
                    found = False
                    for user in users:
                        d = user.to_dict()
                        st.session_state.update({'logged_in':True, 'role':'siswa', 'nama':d['nama_lengkap'], 'username':d['username']})
                        found = True; st.rerun()
                    if not found: st.error("Akun tidak ditemukan")

def admin_dashboard():
    st.markdown("<div class='custom-header'><h3>Dashboard Admin</h3><button onclick='window.location.reload()'>Keluar</button></div>", unsafe_allow_html=True)
    if st.button("Keluar"): st.session_state.clear(); st.rerun()
    
    tab1, tab2, tab3 = st.tabs(["📝 Input Soal (+Gambar)", "📂 Upload CSV", "📊 Data Nilai"])
    
    with tab1:
        st.subheader("Input Soal Manual")
        with st.form("manual_input"):
            c1, c2, c3 = st.columns(3)
            mapel = c1.selectbox("Mapel", ["Matematika", "Bahasa Indonesia"])
            paket = c2.text_input("Paket (Misal: Paket 1)", "Paket 1")
            tipe = c3.selectbox("Tipe Soal", ["Pilihan Ganda (PG)", "PG Kompleks", "Benar/Salah"])
            
            tanya = st.text_area("Pertanyaan Soal")
            gambar = st.file_uploader("Upload Gambar Soal (Jika ada)", type=['png', 'jpg', 'jpeg'])
            
            opsi = []; kunci = None
            st.divider()
            
            if tipe == "Pilihan Ganda (PG)":
                cols = st.columns(4)
                opsi = [cols[i].text_input(f"Opsi {chr(65+i)}") for i in range(4)]
                ans = st.radio("Kunci Jawaban", ["A", "B", "C", "D"], horizontal=True)
                if opsi[0]: kunci = opsi[ord(ans)-65]
                real_tipe = 'single'
                
            elif tipe == "PG Kompleks":
                cols = st.columns(4); chks = st.columns(4)
                kunci_list = []
                for i in range(4):
                    val = cols[i].text_input(f"Pilihan {i+1}")
                    if val: opsi.append(val)
                    if chks[i].checkbox(f"Benar? {i+1}"): kunci_list.append(val)
                kunci = kunci_list
                real_tipe = 'complex'
                
            elif tipe == "Benar/Salah":
                p1 = st.text_input("Pernyataan 1"); k1 = st.radio("Kunci 1", ["Benar","Salah"], horizontal=True, key="k1")
                p2 = st.text_input("Pernyataan 2"); k2 = st.radio("Kunci 2", ["Benar","Salah"], horizontal=True, key="k2")
                opsi = [p1, p2]; kunci = {p1: k1, p2: k2}
                real_tipe = 'category'
            
            if st.form_submit_button("Simpan Soal"):
                img_data = process_image(gambar)
                db.collection('questions').add({
                    'mapel': mapel, 'paket': paket, 'tipe': real_tipe,
                    'pertanyaan': tanya, 'gambar': img_data,
                    'opsi': json.dumps(opsi), 'kunci_jawaban': json.dumps(kunci)
                })
                st.success("Soal Tersimpan!")

    with tab2:
        st.subheader("Upload CSV Massal")
        st.info("Gunakan format CSV yang baru. Jika soal punya gambar, setelah upload CSV, edit soal tersebut di menu Input Manual untuk menambahkan gambarnya.")
        up = st.file_uploader("File CSV", type=['csv'])
        if up and st.button("Proses CSV"):
            try:
                df = pd.read_csv(up)
                count = 0
                for _, row in df.iterrows():
                    # Parsing CSV Pintar
                    o_list = [str(row[c]) for c in ['pilihan_a','pilihan_b','pilihan_c','pilihan_d'] if pd.notna(row[c])]
                    
                    rt = 'single'
                    raw_k = str(row['jawaban_benar'])
                    fk = raw_k
                    
                    if 'Check' in str(row['tipe']): 
                        rt = 'complex'; fk = [x.strip() for x in raw_k.split(',')]
                    elif 'Benar' in str(row['tipe']):
                        rt = 'category'
                        ks = [x.strip() for x in raw_k.split(',')]
                        fk = {o_list[0]: ks[0], o_list[1]: ks[1], o_list[2]: ks[2]} if len(ks)>2 else {} # Handle 3 statements
                    
                    db.collection('questions').add({
                        'mapel': row['mapel'], 'paket': 'Paket 1', 'tipe': rt,
                        'pertanyaan': row['pertanyaan'], 'gambar': None,
                        'opsi': json.dumps(o_list), 'kunci_jawaban': json.dumps(fk)
                    })
                    count += 1
                st.success(f"Berhasil upload {count} soal!")
            except Exception as e: st.error(f"Gagal: {e}")

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
    
    # CARD MATEMATIKA
    with c1:
        st.info("📐 **Matematika**")
        if st.button("Mulai Paket 1 (30 Soal)"):
            if init_exam("Matematika", "Paket 1"): st.rerun()
            
    # CARD B. INDO
    with c2:
        st.success("📖 **Bahasa Indonesia**")
        st.write("(Soal belum diinput)")

def exam_interface():
    # Load Data
    data = st.session_state['exam_data']
    order = st.session_state['q_order']
    idx = st.session_state['curr_idx']
    
    # 1. HEADER & TIMER
    rem = data['end_time'] - datetime.now().timestamp()
    if rem <= 0: finish_exam()
    
    mins, secs = divmod(int(rem), 60)
    
    col_h1, col_h2, col_h3 = st.columns([6, 2, 2])
    with col_h1: st.markdown(f"**{data['mapel']}** | No. {idx+1} dari {len(order)}")
    with col_h2: st.markdown(f"<div style='background:#dbeafe; color:#1e40af; padding:5px; border-radius:5px; text-align:center; font-weight:bold;'>⏱️ {mins:02d}:{secs:02d}</div>", unsafe_allow_html=True)
    with col_h3: 
        fs = st.columns(3)
        if fs[0].button("A-"): st.session_state['font_size'] = '14px'; st.rerun()
        if fs[1].button("A"): st.session_state['font_size'] = '18px'; st.rerun()
        if fs[2].button("A+"): st.session_state['font_size'] = '24px'; st.rerun()
        
    st.divider()
    
    # 2. AREA SOAL (Kiri) & NAVIGASI (Kanan)
    c_soal, c_nav = st.columns([3, 1])
    
    with c_soal:
        qid = order[idx]
        q_doc = db.collection('questions').document(qid).get()
        if q_doc.exists:
            q = q_doc.to_dict()
            
            # Container Soal
            st.markdown(f"<div class='soal-container'>", unsafe_allow_html=True)
            st.write(q['pertanyaan'])
            
            # TAMPILKAN GAMBAR (JIKA ADA)
            if q.get('gambar'):
                st.image(q['gambar'], use_column_width=True)
            
            st.write("") # Spacer
            
            # INPUT JAWABAN
            opsi = json.loads(q['opsi'])
            ans = st.session_state['answers'].get(qid)
            
            if q['tipe'] == 'single':
                sel = st.radio("Jawaban:", opsi, key=qid, index=opsi.index(ans) if ans in opsi else None)
                if sel: st.session_state['answers'][qid] = sel
                
            elif q['tipe'] == 'complex':
                st.write("**Pilih lebih dari satu:**")
                sel = ans if isinstance(ans, list) else []
                new_sel = []
                for o in opsi:
                    if st.checkbox(o, o in sel, key=f"{qid}_{o}"): new_sel.append(o)
                st.session_state['answers'][qid] = new_sel
                
            elif q['tipe'] == 'category':
                st.write("**Tentukan Benar/Salah:**")
                sel = ans if isinstance(ans, dict) else {}
                new_sel = {}
                for o in opsi:
                    c_a, c_b = st.columns([3,1])
                    c_a.write(o)
                    val = c_b.radio(f"opt_{o}", ["Benar","Salah"], key=f"{qid}_{o}", horizontal=True, label_visibility="collapsed",
                                    index=0 if sel.get(o)=="Benar" else 1 if sel.get(o)=="Salah" else None)
                    if val: new_sel[o] = val
                st.session_state['answers'][qid] = new_sel
            
            st.markdown("</div>", unsafe_allow_html=True)

    with c_nav:
        st.write("Navigasi Soal")
        cols = st.columns(5)
        for i, q_id in enumerate(order):
            style = ""
            # Cek status (Hijau jika dijawab, Kuning jika Ragu)
            if q_id in st.session_state['answers'] and st.session_state['answers'][q_id]:
                style = "status-done"
            if q_id in st.session_state['ragu']:
                style = "status-ragu"
            if i == idx:
                style += " status-current"
                
            if cols[i%5].button(f"{i+1}", key=f"nav_{i}"):
                st.session_state['curr_idx'] = i; save_realtime(); st.rerun()
        
        st.markdown("---")
        # Tombol Ragu & Navigasi Bawah
        is_ragu = qid in st.session_state['ragu']
        if st.button(f"{'🟨 Batal Ragu' if is_ragu else '🟨 Ragu-Ragu'}", use_container_width=True):
            if is_ragu: st.session_state['ragu'].remove(qid)
            else: st.session_state['ragu'].append(qid)
            save_realtime(); st.rerun()
            
        c_p, c_n = st.columns(2)
        if idx > 0:
            if c_p.button("⬅️ Sblm", use_container_width=True):
                st.session_state['curr_idx'] -= 1; save_realtime(); st.rerun()
        
        if idx < len(order)-1:
            if c_n.button("Lanjut ➡️", use_container_width=True):
                st.session_state['curr_idx'] += 1; save_realtime(); st.rerun()
        else:
            if c_n.button("✅ Selesai", type="primary", use_container_width=True):
                finish_exam()

def result_interface():
    st.balloons()
    st.success(f"Ujian Selesai! Nilai Kamu: {st.session_state['last_score']:.1f}")
    if st.button("Kembali ke Beranda"):
        st.session_state['result_mode'] = False; st.rerun()
    with st.expander("Lihat Pembahasan"):
        st.json(st.session_state['last_det'])

if __name__ == "__main__":
    main()
