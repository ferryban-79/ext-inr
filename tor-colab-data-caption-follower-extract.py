# ╔══════════════════════════════════════════════════════════════════════════╗
# ║     UNIVERSAL INSTAGRAM EXTRACTOR - PRO AUTO-BATCH & ORGANIZER           ║
# ║  Modules: RawData | CleanData | Following | Suggested | Tagged Posts     ║
# ║  Features: Auto-Move JSONs | Dynamic Batch Folder | 12-Threads Parallel  ║
# ╚══════════════════════════════════════════════════════════════════════════╝

import os, json, re, glob, requests, csv, sys, signal, threading, shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# ════════════════════════════════════════════════════════════════════
#  SECTION 1 ── DYNAMIC PATH & BATCH CONFIG
# ════════════════════════════════════════════════════════════════════
BASE_DIR   = '.'
# ── Matrix worker se env var aata hai — warna default ──
INPUT_FOLDER = os.environ.get("INPUT_FOLDER",  os.path.join(BASE_DIR, 'datasets'))

# Script ki apni location (loose JSON files dhoondne ke liye)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Real-time Batch Folder — worker.py se env var aata hai, warna naya banao
now = datetime.now()
folder_timestamp  = now.strftime("%Y-%m-%d-%A_%I-%M-%S-%p")
BATCH_FOLDER_NAME = f"Batch--{folder_timestamp}"
OUTPUT_FOLDER     = os.environ.get("OUTPUT_FOLDER", os.path.join(BASE_DIR, BATCH_FOLDER_NAME))

# --- Limits & Behaviour ---
MAX_WORKERS    = int(os.environ.get("MAX_WORKERS", "30"))  # matrix: 30 per node
DOWNLOAD_MEDIA = True
ITEM_LIMIT     = 5000000000
MAX_PFP_PER_RUN = 99999999
FOLLOWING_MODE  = 'straight'
STATE_FILE      = os.path.join(OUTPUT_FOLDER, "resume_state.json")

# ════════════════════════════════════════════════════════════════════
#  SECTION 2 ── AUTO-ORGANIZER  (Loose JSON → datasets folder)
# ════════════════════════════════════════════════════════════════════
def organize_input_files():
    os.makedirs(INPUT_FOLDER, exist_ok=True)
    # Search dirs mein 'Inputs' add kiya gaya hai
    search_dirs = set([SCRIPT_DIR, '/data', os.path.join(BASE_DIR, 'Inputs')])
    loose_jsons = []
    for d in search_dirs:
        if os.path.exists(d):
            loose_jsons += glob.glob(os.path.join(d, '*.json'))

    SKIP_NAMES = {'resume_state.json', 'package.json', 'package-lock.json'}
    moved_count = 0

    for file_path in loose_jsons:
        file_name = os.path.basename(file_path)
        if file_name in SKIP_NAMES:
            continue
        # Agar file already INPUT_FOLDER ke andar hai to skip
        if os.path.abspath(file_path) == os.path.abspath(os.path.join(INPUT_FOLDER, file_name)):
            continue
        dest_path = os.path.join(INPUT_FOLDER, file_name)
        try:
            shutil.move(file_path, dest_path)
            moved_count += 1
            print(f"   📦 Moved: {file_name}  →  datasets/")
        except Exception as e:
            print(f"   ⚠️  Error moving {file_name}: {e}")

    if moved_count > 0:
        print(f"\n📦 [ORGANIZER] {moved_count} loose JSON file(s) moved to: {INPUT_FOLDER}\n")

# ════════════════════════════════════════════════════════════════════
#  SECTION 3 ── PLATFORM DETECTION & SIGNAL SETUP
# ════════════════════════════════════════════════════════════════════
try:
    import msvcrt
    WINDOWS_OS = True
except ImportError:
    WINDOWS_OS = False

os.makedirs(INPUT_FOLDER,  exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

shutdown_flag  = False
skip_file_flag = False

print_lock  = threading.Lock()
csv_lock    = threading.Lock()
state_lock  = threading.Lock()
cache_lock  = threading.Lock()

def safe_print(*args, **kwargs):
    with print_lock:
        try:
            msg = " ".join(str(a) for a in args)
            sys.stdout.buffer.write((msg + "\n").encode('utf-8', errors='replace'))
            sys.stdout.buffer.flush()
        except Exception:
            try: print(*args, **kwargs)
            except Exception: pass

def _signal_handler(sig, frame):
    global shutdown_flag
    safe_print("\n\n🛑 [CTRL+C] Safely stopping threads... Please wait.")
    shutdown_flag = True

signal.signal(signal.SIGINT, _signal_handler)

def _check_hotkey():
    global skip_file_flag
    if WINDOWS_OS and msvcrt.kbhit():
        key = msvcrt.getch().decode('utf-8', 'ignore').lower()
        if key == 'f':
            skip_file_flag = True
            return 'f'
    return None

# ════════════════════════════════════════════════════════════════════
#  SECTION 4 ── COMMON HELPERS
# ════════════════════════════════════════════════════════════════════
def sanitize(text, max_length=40):
    if not text: return ''
    text = str(text).replace('\n', ' ').replace('\r', '')
    text = re.sub(r'[\\/*?:"<>|.,\[\]\(\)\'!@#$%\^&\-+=`~؛،؟]', '', text)
    text = text.replace('\u200f', '').replace('\u200e', '').replace('\u200b', '')
    text = text.strip().replace(' ', '_')
    text = re.sub(r'_+', '_', text)
    return text[:max_length].strip('_')

def sanitize_or(text, fallback, max_length=40):
    result = sanitize(text, max_length)
    return result if result else fallback

def format_timestamp(ts):
    if not ts: return "0000-00-00_00-00-00"
    try:
        if isinstance(ts, str) and 'T' in ts:
            if '.' in ts and ts.endswith('Z'):
                dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")
            else:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            return dt.strftime('%Y-%m-%d_%H-%M-%S')
        ts_int = int(str(ts)[:10])
        return datetime.fromtimestamp(ts_int).strftime('%Y-%m-%d_%H-%M-%S')
    except Exception:
        return str(ts).replace('T','_').replace('Z','').replace(':','-')[:19]

def download(url, path):
    if not url or os.path.exists(path) or not DOWNLOAD_MEDIA: return False
    if not isinstance(url, str) or not url.startswith('http'): return False
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        if r.status_code == 200:
            with open(path, 'wb') as f: f.write(r.content)
            return True
    except Exception:
        pass
    return False

# ════════════════════════════════════════════════════════════════════
#  SECTION 5 ── RESUME STATE MANAGER
# ════════════════════════════════════════════════════════════════════
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=4)
    except Exception:
        pass

def _write_txt_report(txt_path, source_file, out_dir, s, total):
    try:
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write("=== PROCESSING REPORT ===\n")
            f.write(f"Source File   : {source_file}\n")
            f.write(f"Output Folder : {out_dir}\n")
            f.write(f"Start Time    : {s.get('start_time')}\n")
            f.write(f"Last Update   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("-------------------------\n")
            f.write(f"Processed     : {s.get('processed_count')} / {total}\n")
            f.write(f"JSONs Saved   : {s.get('json_saved')}\n")
            f.write(f"PFPs Downloaded  : {s.get('pfps_downloaded')}\n")
            f.write(f"PFPs Skipped  : {s.get('pfps_skipped_exists')}\n")
            f.write(f"PFPs Failed   : {s.get('pfps_failed')}\n")
            f.write("-------------------------\n")
    except Exception:
        pass

# ════════════════════════════════════════════════════════════════════
#  SECTION 6 ── GLOBAL AVATAR CACHE (Thread Safe)
# ════════════════════════════════════════════════════════════════════
_avatar_cache = {}

def update_avatar_cache(user_dict):
    if not isinstance(user_dict, dict): return
    uname = user_dict.get('username')
    if not uname: return

    with cache_lock:
        best = _avatar_cache.get(uname, {'url': None, 'width': 0})

        hd_info = user_dict.get('hd_profile_pic_url_info')
        if isinstance(hd_info, dict) and hd_info.get('url'):
            w = hd_info.get('width', 1080)
            if w > best['width']:
                _avatar_cache[uname] = {'url': hd_info['url'], 'width': w}

        hd_vers = user_dict.get('hd_profile_pic_versions')
        if isinstance(hd_vers, list) and hd_vers:
            pic = sorted(hd_vers, key=lambda x: x.get('width', 0), reverse=True)[0]
            w   = pic.get('width', 0)
            if pic.get('url') and w > best['width']:
                _avatar_cache[uname] = {'url': pic['url'], 'width': w}

        normal = user_dict.get('profile_pic_url') or user_dict.get('profilePicUrl')
        if normal and _avatar_cache.get(uname, {'width': 0})['width'] == 0:
            _avatar_cache[uname] = {'url': normal, 'width': 150}

def get_best_avatar(username):
    with cache_lock:
        return _avatar_cache.get(username, {}).get('url')

# ════════════════════════════════════════════════════════════════════
#  SECTION 7 ── SMART MEDIA EXTRACTORS
# ════════════════════════════════════════════════════════════════════
def _extract_video(node):
    for key in ('videoUrl', 'video_url'):
        if node.get(key): return node[key]
    vers = node.get('video_versions')
    if isinstance(vers, list) and vers:
        return vers[0].get('url')
    return None

def _extract_image(node):
    for key in ('displayUrl', 'display_url'):
        if node.get(key): return node[key]
    iv2 = node.get('image_versions2')
    if isinstance(iv2, dict):
        cands = iv2.get('candidates', [])
        if cands: return cands[0].get('url')
    if node.get('thumbnail_src'): return node['thumbnail_src']
    dr = node.get('display_resources')
    if isinstance(dr, list) and dr: return dr[-1].get('src')
    return None

def get_media_list_raw(item):
    out, seen = [], set()
    def _add(url, mtype, role):
        if url and url not in seen:
            seen.add(url); out.append({'url': url, 'type': mtype, 'role': role})

    if 'edge_sidecar_to_children' in item:
        for edge in item['edge_sidecar_to_children'].get('edges', []):
            n    = edge.get('node', {})
            is_v = n.get('is_video') or n.get('video_versions') or n.get('media_type') == 2
            if is_v:
                _add(_extract_video(n), 'mp4', 'item')
                _add(_extract_image(n), 'jpg', 'item')
            else:
                _add(_extract_image(n), 'jpg', 'item')
    elif 'carousel_media' in item:
        for child in item['carousel_media']:
            is_v = child.get('is_video') or child.get('video_versions') or child.get('media_type') == 2
            if is_v:
                _add(_extract_video(child), 'mp4', 'item')
                _add(_extract_image(child), 'jpg', 'item')
            else:
                _add(_extract_image(child), 'jpg', 'item')
    else:
        is_v = (item.get('is_video') or item.get('product_type') == 'clips'
                or item.get('video_versions') or item.get('media_type') == 2)
        if is_v:
            _add(_extract_video(item), 'mp4', 'reels')
            _add(_extract_image(item), 'jpg', 'thumbs')
        else:
            _add(_extract_image(item), 'jpg', 'item')
    return out

def get_media_list_clean(item):
    out, seen = [], set()
    itype = item.get('type', '')
    def _add(url, mtype, label):
        if url and url not in seen:
            seen.add(url); out.append({'url': url, 'type': mtype, 'label': label})

    if itype == 'Sidecar' or item.get('carouselSlides'):
        slides = item.get('carouselSlides') or []
        if not slides:
            for i, img in enumerate(item.get('images', [])):
                _add(img, 'jpg', f'slide{i+1}')
        else:
            for i, sl in enumerate(slides):
                n = i + 1
                if sl.get('type') == 'Video' or sl.get('videoUrl'):
                    _add(sl.get('videoUrl'), 'mp4', f'slide{n}')
                    _add(sl.get('displayUrl') or sl.get('thumbnailUrl'), 'jpg', f'slide{n}_thumb')
                else:
                    _add(sl.get('displayUrl') or sl.get('url'), 'jpg', f'slide{n}')
    elif itype == 'Video' or item.get('videoUrl') or item.get('is_video'):
        _add(item.get('videoUrl') or item.get('video_url'), 'mp4', 'reels')
        _add(item.get('displayUrl') or item.get('display_url') or item.get('thumbnailUrl'), 'jpg', 'thumbs')
    else:
        img = item.get('displayUrl') or item.get('display_url') or item.get('thumbnail_src')
        if not img:
            imgs = item.get('images', [])
            if imgs: img = imgs[0]
        _add(img, 'jpg', 'slide1')
    return out

def get_caption(item):
    try:
        edges = item.get('edge_media_to_caption', {}).get('edges', [])
        if edges: return edges[0].get('node', {}).get('text', '')
    except Exception:
        pass
    cap = item.get('caption')
    if isinstance(cap, dict): return cap.get('text', '')
    if isinstance(cap, str) and cap: return cap
    txt = item.get('text')
    if isinstance(txt, str): return txt
    return ''

# ════════════════════════════════════════════════════════════════════
#  SECTION 7b ── ENTERPRISE METRICS EXTRACTOR
# ════════════════════════════════════════════════════════════════════
def get_best_metric(node, keys):
    """Deep metric extractor — handles both dict-count and direct int formats."""
    for key in keys:
        val = node.get(key)
        if val is None: continue
        # Format 1: {'count': 123}
        if isinstance(val, dict) and 'count' in val:
            try: return int(val['count'])
            except: pass
        # Format 2: direct integer (e.g. video_view_count: 1633480)
        if isinstance(val, (int, float)):
            try: return int(val)
            except: pass
        # Format 3: numeric string
        if isinstance(val, str) and val.strip().lstrip('-').isdigit():
            try: return int(val.strip())
            except: pass
    # Try one level deeper in common wrapper keys
    for sub in ('xdt_shortcode_media', 'media_or_ad', 'media'):
        sub_node = node.get(sub)
        if isinstance(sub_node, dict):
            result = get_best_metric(sub_node, keys)
            if result is not None: return result
    return None

# ════════════════════════════════════════════════════════════════════
#  SECTION 8 ── IN-MEMORY TAGGER & DEEP TRAVERSAL
# ════════════════════════════════════════════════════════════════════
def tag_active_stories_and_highlights(data):
    if not isinstance(data, dict): return

    active_stories = data.get('activeStories')
    if active_stories:
        if isinstance(active_stories, dict):
            for key in ["reels", "reels_media"]:
                reel_data = active_stories.get(key, {})
                if isinstance(reel_data, dict):
                    for reel_val in reel_data.values():
                        if isinstance(reel_val, dict):
                            for st in reel_val.get("items", []):
                                if isinstance(st, dict): st['_is_active_story'] = True
                elif isinstance(reel_data, list):
                    for reel_val in reel_data:
                        if isinstance(reel_val, dict):
                            for st in reel_val.get("items", []):
                                if isinstance(st, dict): st['_is_active_story'] = True
        elif isinstance(active_stories, list):
            for item in active_stories:
                if isinstance(item, dict):
                    if "items" in item:
                        for st in item.get("items", []):
                            if isinstance(st, dict): st['_is_active_story'] = True
                    else:
                        item['_is_active_story'] = True

    highlights = data.get('highlights', [])
    if isinstance(highlights, list):
        for hl in highlights:
            if isinstance(hl, dict):
                if 'items' in hl:
                    title = sanitize_or(hl.get('title', ''), 'Unknown', 25)
                    for it in hl['items']:
                        if isinstance(it, dict):
                            it['_is_highlight']    = True
                            it['_highlight_title'] = title
                else:
                    raw_hl    = hl.get('highlight', {})
                    raw_media = hl.get('rawMedia', [])
                    title     = sanitize_or(raw_hl.get('title', '') if isinstance(raw_hl, dict) else '', 'Unknown', 25)
                    for st in raw_media:
                        if isinstance(st, dict):
                            st['_is_highlight']    = True
                            st['_highlight_title'] = title

def extract_comments_globally(data):
    cmap, seen = {}, set()
    def _add(pid, c):
        if not pid or not isinstance(c, dict): return
        key = str(c.get('id') or c.get('pk') or c.get('text', ''))
        if key and key not in seen:
            seen.add(key)
            cmap.setdefault(pid, []).append(c)

    # ── FIX A: Master Dataset {data:[{shortcode, raw_comments_list, raw_post_data}]} ──
    # Comments pk/id se deduplicate karke shortcode aur numeric_id dono se map karna
    if isinstance(data, dict) and isinstance(data.get('data'), list):
        _sc_seen = {}  # shortcode -> set of pks (per-shortcode dedup)
        for entry in data['data']:
            if not isinstance(entry, dict): continue
            sc = entry.get('shortcode', '')
            raw_cmts = entry.get('raw_comments_list') or []
            if not (sc and raw_cmts): continue
            if sc not in _sc_seen: _sc_seen[sc] = set()
            for c in raw_cmts:
                ck = str(c.get('pk') or c.get('id') or c.get('text',''))
                if ck and ck not in _sc_seen[sc]:
                    _sc_seen[sc].add(ck)
                    cmap.setdefault(sc, []).append(c)
                    seen.add(ck)
            # xdt_shortcode_media ka numeric id se bhi map karo
            rp = entry.get('raw_post_data')
            if isinstance(rp, dict):
                xdt = (rp.get('data') or {}).get('xdt_shortcode_media') or {}
                nid = str(xdt.get('id') or xdt.get('pk') or '')
                if nid and nid != sc:
                    for c in cmap.get(sc, []):
                        _add(nid, c)
    # ── END FIX A ───────────────────────────────────────────────────

    def _walk(obj, cur_pid=None):
        if isinstance(obj, dict):
            if 'username' in obj and ('profile_pic_url' in obj or 'hd_profile_pic_url_info' in obj):
                update_avatar_cache(obj)
            if 'owner' in obj: update_avatar_cache(obj['owner'])
            if 'user'  in obj: update_avatar_cache(obj['user'])

            # NEW LOGIC HANDLER ADDED HERE (Original bacha kar rakha hai)
            pid = str(obj.get('id') or obj.get('pk') or obj.get('shortcode') or '')
            if '_' in pid and not pid.startswith('item_'): pid = pid.split('_')[0]

            is_post = (any(k in obj for k in ('display_url','video_url','image_versions2','raw_comments_list'))
                       and not ('text' in obj and 'created_at' in obj))
            if pid and is_post: cur_pid = pid

            if 'raw_comments_list' in obj and isinstance(obj['raw_comments_list'], list):
                for c in obj['raw_comments_list']:
                    _add(pid or cur_pid, c)
            # END OF NEW LOGIC HANDLER

            if 'text' in obj and 'created_at' in obj and ('owner' in obj or 'user' in obj):
                cpid = str(obj.get('media_id') or cur_pid or '')
                if '_' in cpid and not cpid.startswith('item_'): cpid = cpid.split('_')[0]
                _add(cpid, obj)

            for v in obj.values(): _walk(v, cur_pid)
        elif isinstance(obj, list):
            for v in obj: _walk(v, cur_pid)
    _walk(data)
    return cmap

def find_raw_posts(data, require_owner=False):
    found = []

    # ── FIX B: Master Dataset format — xdt_shortcode_media ko post ki tarah extract karna ──
    if isinstance(data, dict) and isinstance(data.get('data'), list):
        for entry in data['data']:
            if not isinstance(entry, dict): continue
            sc  = entry.get('shortcode', '')
            rp  = entry.get('raw_post_data')
            xdt = None
            if isinstance(rp, dict):
                xdt = (rp.get('data') or {}).get('xdt_shortcode_media')
            if isinstance(xdt, dict) and xdt.get('id'):
                if sc and not xdt.get('shortcode'):
                    xdt = dict(xdt)        # mutate mat karo original ko
                    xdt['shortcode'] = sc
                found.append(xdt)
    # ── END FIX B ───────────────────────────────────────────────────

    def _walk(obj, in_carousel=False):
        if isinstance(obj, dict):
            if in_carousel:
                for v in obj.values(): _walk(v, True)
                return

            pid = str(obj.get('id') or obj.get('pk') or obj.get('shortcode') or '')
            is_comment = 'text' in obj and 'created_at' in obj
            has_media   = any(k in obj for k in (
                'display_url','video_url','image_versions2',
                'carousel_media','edge_sidecar_to_children','taken_at_timestamp'))

            owner     = obj.get('owner') or obj.get('user') or {}
            has_owner = isinstance(owner, dict) and ('username' in owner or 'id' in owner)

            ok = pid and not is_comment and has_media
            if require_owner: ok = ok and has_owner

            if ok:
                found.append(obj)
                has_car = 'edge_sidecar_to_children' in obj or 'carousel_media' in obj
                for k, v in obj.items():
                    if k not in ('edge_media_to_comment', 'edge_media_preview_comment'):
                        _walk(v, in_carousel=has_car)
            else:
                for k, v in obj.items():
                    if k not in ('edge_media_to_comment', 'edge_media_preview_comment'):
                        _walk(v, False)
        elif isinstance(obj, list):
            for v in obj: _walk(v, in_carousel)
    _walk(data, False)
    return found

def extract_active_stories_advanced(data):
    story_items  = []
    if not isinstance(data, dict):
        return story_items
    active_stories = data.get('activeStories')
    if not active_stories: return story_items

    if isinstance(active_stories, dict):
        for key in ["reels", "reels_media"]:
            reel_data = active_stories.get(key, {})
            if isinstance(reel_data, dict):
                for reel_val in reel_data.values():
                    if isinstance(reel_val, dict):
                        for st in reel_val.get("items", []):
                            st['product_type']    = 'story'
                            st['_is_active_story'] = True
                            story_items.append(st)
            elif isinstance(reel_data, list):
                for reel_obj in reel_data:
                    if isinstance(reel_obj, dict):
                        for st in reel_obj.get("items", []):
                            st['product_type']    = 'story'
                            st['_is_active_story'] = True
                            story_items.append(st)
    elif isinstance(active_stories, list):
        for item in active_stories:
            if isinstance(item, dict):
                if "items" in item:
                    for st in item.get("items", []):
                        st['product_type']    = 'story'
                        st['_is_active_story'] = True
                        story_items.append(st)
                else:
                    item['product_type']    = 'story'
                    item['_is_active_story'] = True
                    story_items.append(item)
    return story_items

# ════════════════════════════════════════════════════════════════════
#  SECTION 9 ── MULTI-THREADED UNIFIED POST DOWNLOADER
# ════════════════════════════════════════════════════════════════════
def _build_filenames(post_node, global_username, media_source='raw'):
    nid = str(post_node.get('id') or post_node.get('pk') or '')
    if '_' in nid and not nid.startswith('item_'): nid = nid.split('_')[0]

    code = str(post_node.get('shortcode') or post_node.get('shortCode') or post_node.get('code') or nid)
    if '_' in code and not code.startswith('item_'): code = code.split('_')[0]

    owner = post_node.get('owner') or post_node.get('user') or {}
    uval  = (owner.get('username') if isinstance(owner, dict) else None) or global_username
    user  = sanitize(uval, 30) or 'user'

    is_hl          = post_node.get('_is_highlight', False)
    is_active_story = post_node.get('_is_active_story', False)

    if not is_hl and not is_active_story:
        if 'highlights_info' in post_node or str(post_node.get('source_type', '')).startswith('Highlight'):
            is_hl = True
        elif post_node.get('product_type') == 'story' or post_node.get('source_type') == 'Story':
            is_active_story = True

    ts_raw = (post_node.get('taken_at_timestamp') or post_node.get('taken_at') or post_node.get('timestamp'))
    ts     = format_timestamp(ts_raw)
    suffix = f"{ts}_{code}"

    if is_hl:
        hl_title_raw = post_node.get('_highlight_title', '')
        if not hl_title_raw:
            added_to = post_node.get('highlights_info', {}).get('added_to', [])
            if added_to and isinstance(added_to, list):
                hl_title_raw = added_to[0].get('title', '')
        hl_title  = sanitize_or(hl_title_raw, 'Unknown', 40)
        base_name = f"@{user}_Highlight_{hl_title}".strip('_')
        cmts_name = None
    elif is_active_story:
        base_name = f"@{user}_ActiveStory".strip('_')
        cmts_name = None
    else:
        cap_raw = get_caption(post_node)
        if not cap_raw:
            c = post_node.get('caption', '')
            cap_raw = c.get('text', '') if isinstance(c, dict) else str(c)
        cap         = sanitize_or(cap_raw, 'NoCaption', 40)
        base_name   = f"@{user}_{cap}"
        cmts_name   = f"{base_name}_comments_{suffix}.json"
        report_name = f"{base_name}_caption_{suffix}.txt"

    meta_name = f"{base_name}_meta_{suffix}.json"

    # For highlights/stories there is no caption report
    if is_hl or is_active_story:
        report_name = None
        cap_raw     = ''

    return {
        'numeric_id': nid, 'base_name': base_name, 'suffix': suffix, 'code': code,
        'meta_name': meta_name, 'cmts_name': cmts_name, 'report_name': report_name,
        'is_highlight': is_hl, 'is_active_story': is_active_story,
        'user': user, 'user_val': uval, 'caption': cap_raw,
    }

def _save_media(post_node, base_name, suffix, out_dir, is_highlight, is_active_story, media_source='raw'):
    if media_source == 'clean':
        media_list = get_media_list_clean(post_node)
        if not media_list:
            v = _extract_video(post_node) or post_node.get('videoUrl')
            i = _extract_image(post_node) or post_node.get('displayUrl')
            if v: media_list.append({'url': v, 'type': 'mp4', 'label': 'reels'})
            if i: media_list.append({'url': i, 'type': 'jpg', 'label': 'slide1'})
    else:
        media_list = get_media_list_raw(post_node)
        if not media_list:
            v = post_node.get('videoUrl') or post_node.get('video_url')
            d = post_node.get('displayUrl') or post_node.get('display_url')
            if v: media_list.append({'url': v, 'type': 'mp4', 'role': 'reels'})
            if d: media_list.append({'url': d, 'type': 'jpg', 'role': 'item'})

    done     = False
    item_ctr = 1

    for m in media_list[:15]:
        if shutdown_flag or skip_file_flag: break
        ext  = m['type']
        role = m.get('role') or m.get('label', 'item')

        if is_highlight:
            if ext == 'mp4' or role in ('reels', 'mp4'):
                fname = f"{base_name}_reel_{suffix}.{ext}"
            elif 'thumb' in role:
                fname = f"{base_name}_reel_thumb_{suffix}.{ext}"
            else:
                fname = f"{base_name}_img_{suffix}.{ext}"
        elif is_active_story:
            if ext == 'mp4' or role in ('reels', 'mp4'):
                fname = f"{base_name}_vid_{suffix}.{ext}"
            elif 'thumb' in role:
                fname = f"{base_name}_vid_thumb_{suffix}.{ext}"
            else:
                fname = f"{base_name}_img_{suffix}.{ext}"
        else:
            if   role == 'reels':  lbl = 'reels'
            elif role == 'thumbs': lbl = 'thumbs'
            elif 'thumb' in role:  lbl = role
            else:
                lbl       = f"item{item_ctr}"
                item_ctr += 1
            fname = f"{base_name}_{lbl}_{suffix}.{ext}"

        if download(m['url'], os.path.join(out_dir, fname)):
            done = True

    return done

def _process_single_post(node, idx, out_dir, global_username, comments_map, media_source):
    global shutdown_flag, skip_file_flag
    if shutdown_flag or skip_file_flag: return

    info = _build_filenames(node, global_username, media_source)
    nid, base, suffix   = info['numeric_id'], info['base_name'], info['suffix']
    meta_name, cmts_name = info['meta_name'], info['cmts_name']
    report_name, full_caption = info['report_name'], info['caption']
    code = info.get('code', nid)
    is_hl, is_active_story = info['is_highlight'], info['is_active_story']
    user, uval = info['user'], info['user_val']

    av_url  = get_best_avatar(uval)
    av_path = os.path.join(out_dir, f"@{user}_avatar.jpg")
    if av_url and not os.path.exists(av_path): download(av_url, av_path)

    meta_path   = os.path.join(out_dir, meta_name)
    cmts_path   = os.path.join(out_dir, cmts_name)   if cmts_name   else None
    report_path = os.path.join(out_dir, report_name) if report_name else None

    # Skip only when meta AND report (for regular posts) already exist
    if report_path:
        already = os.path.exists(meta_path) and os.path.exists(report_path)
    else:
        already = os.path.exists(meta_path)

    if already:
        safe_print(f"      [{idx+1}] ⏭️  SKIPPED (exists): {meta_name}")
        return

    # 1. Save Meta JSON
    save_node = {k: v for k, v in node.items() if k not in ('_is_highlight', '_highlight_title', '_is_active_story')}
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(save_node, f, indent=4, ensure_ascii=False)

    # 2. Gather comments — id + shortcode dono se, duplicate-free
    _cmap_by_id = comments_map.get(nid, [])
    _cmap_by_sc = comments_map.get(code, []) if (code and code != nid) else []
    _seen_cmts  = {}
    for _c in _cmap_by_id + _cmap_by_sc:
        _ck = str(_c.get('pk') or _c.get('id') or _c.get('text',''))
        if _ck not in _seen_cmts:
            _seen_cmts[_ck] = _c
    post_cmts = list(_seen_cmts.values())
    # END OF GATHER COMMENTS (original NEW LOGIC HANDLER replaced with dedup version)

    if media_source == 'clean':
        for ckey in ('comments', 'latestComments', 'extractedComments'):
            if ckey in node and isinstance(node[ckey], list):
                seen_ids = set()
                for c in node[ckey]:
                    cid = str(c.get('id') or c.get('pk') or c.get('text', ''))
                    if cid not in seen_ids:
                        seen_ids.add(cid); post_cmts.append(c)

    if cmts_path:
        with open(cmts_path, 'w', encoding='utf-8') as f:
            json.dump(post_cmts, f, indent=4, ensure_ascii=False)

    # 3. Enterprise Metrics & Caption Report (regular posts only)
    if report_path:
        likes = get_best_metric(node, ['edge_media_preview_like', 'edge_liked_by', 'like_count']) or 0
        comments_count = get_best_metric(node, ['edge_media_to_parent_comment', 'comment_count']) or len(post_cmts) or 0
        v_val = get_best_metric(node, ['video_view_count', 'view_count', 'edge_media_to_view_count'])
        p_val = get_best_metric(node, ['video_play_count', 'play_count', 'edge_media_to_play_count'])
        views = f"{v_val:,}" if v_val is not None else "N/A"
        plays = f"{p_val:,}" if p_val is not None else "N/A"

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(f"{'='*60}\n📊 ENTERPRISE METRICS & CAPTION REPORT\n{'='*60}\n")
            f.write(f"🔗 Link     : https://www.instagram.com/p/{code}/\n")
            f.write(f"👤 User     : @{user}\n")
            f.write(f"🆔 ID       : {nid}\n")
            f.write(f"🔑 Code     : {code}\n")
            f.write(f"{'-'*30}\n")
            f.write(f"❤️  Likes    : {likes:,}\n")
            f.write(f"💬 Comments : {comments_count:,}\n")
            f.write(f"▶️  Plays    : {plays}\n")
            f.write(f"👁️  Views    : {views}\n")
            f.write(f"{'-'*30}\n📝 CAPTION:\n{full_caption}\n")
            f.write(f"{'='*60}\n")

    # 4. Download Media
    done = _save_media(node, base, suffix, out_dir, is_hl, is_active_story, media_source)

    if is_hl:
        status = "✅ (Highlight)" if done else "Meta Only (Highlight)"
    elif is_active_story:
        status = "✅ (Active Story)" if done else "Meta Only (Active Story)"
    else:
        cs = f"(+{len(post_cmts)} Comments)" if post_cmts else "(0 Comments)"
        status = f"✅ Saved {cs} & Report" if done else f"✅ Meta & Report Saved {cs}"

    safe_print(f"      [{idx+1}] → {meta_name} ... {status}")

def _download_posts_batch(posts_list, out_dir, global_username, comments_map=None, media_source='raw'):
    global skip_file_flag
    skip_file_flag = False
    if comments_map is None: comments_map = {}
    import time

    posts_to_process = posts_list[:ITEM_LIMIT]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_idx = {}
        for idx, node in enumerate(posts_to_process):
            if isinstance(node, dict):
                f = executor.submit(
                    _process_single_post, node, idx, out_dir, global_username, comments_map, media_source)
                future_to_idx[f] = idx

        pending = list(future_to_idx.keys())
        while pending:
            if shutdown_flag: break
            key = _check_hotkey()
            if key == 'f':
                safe_print("\n   ⏭️ [F] File skipped by user. Cancelling remaining tasks...")
                break
            done_now = [f for f in pending if f.done()]
            for f in done_now:
                try:
                    f.result()
                except Exception as e:
                    idx = future_to_idx[f]
                    safe_print(f"      [{idx+1}] ❌ ERROR: {e}")
            pending = [f for f in pending if not f.done()]
            time.sleep(0.05)

    return len(posts_to_process)

# ════════════════════════════════════════════════════════════════════
#  MODULE A ── RAW DATA PROCESSOR
# ════════════════════════════════════════════════════════════════════
def module_rawdata(data, out_dir, username):
    safe_print("   📋 [RAW] Extracting posts, highlights, stories...")

    tag_active_stories_and_highlights(data)
    comments_map = extract_comments_globally(data)

    # ── FIX C: Alag _comments_ JSON files se comments merge karna ──
    # File naming pattern: @username_caption_comments_DATE_SHORTCODE.json
    # Ye files datasets folder mein ya script ke sath hoti hain
    _comment_file_dirs = [INPUT_FOLDER, SCRIPT_DIR, BASE_DIR]
    for _cdir in _comment_file_dirs:
        for _cfile in glob.glob(os.path.join(_cdir, '*_comments_*.json')):
            try:
                _cbase = os.path.basename(_cfile)
                # Shortcode filename ke last underscore-separated part mein hota hai
                # Example: _tomasnoi_..._comments_2026-02-16_06-26-07_DUzN32XCGBE.json
                _parts = _cbase.replace('.json','').split('_')
                _sc    = _parts[-1] if _parts else ''
                if not _sc or len(_sc) < 5: continue
                with open(_cfile, 'r', encoding='utf-8') as _f:
                    _cmts = json.load(_f)
                if not isinstance(_cmts, list): continue
                _loaded = 0
                for _c in _cmts:
                    if not isinstance(_c, dict): continue
                    _key = str(_c.get('id') or _c.get('pk') or _c.get('text',''))
                    # shortcode se map karo
                    _existing = comments_map.get(_sc, [])
                    _ex_keys  = {str(x.get('id') or x.get('pk') or x.get('text','')) for x in _existing}
                    if _key and _key not in _ex_keys:
                        comments_map.setdefault(_sc, []).append(_c)
                        _loaded += 1
                if _loaded:
                    safe_print(f"   📎 [COMMENT FILE] +{_loaded} comments loaded from: {_cbase}")
            except Exception:
                pass
    # ── END FIX C ────────────────────────────────────────────────────

    acc = None
    if isinstance(data, dict):
        acc = data.get('accountInfo') or data.get('user')

    if isinstance(acc, dict) and ('username' in acc or 'Username' in acc):
        uname_from_acc = acc.get('username') or acc.get('Username') or username
        with open(os.path.join(out_dir, "PROFILE_INFO.json"), 'w', encoding='utf-8') as f:
            json.dump(acc, f, indent=4, ensure_ascii=False)
        update_avatar_cache(acc)
        av = get_best_avatar(uname_from_acc)
        if av: download(av, os.path.join(out_dir, f"@{uname_from_acc}_avatar.jpg"))

    raw_posts   = find_raw_posts(data, require_owner=False)
    raw_stories = extract_active_stories_advanced(data)
    if raw_stories:
        raw_posts.extend(raw_stories)

    unique_posts = {}
    for post_node in raw_posts:
        numeric_id = str(post_node.get('id') or post_node.get('pk') or "")
        if '_' in numeric_id and not numeric_id.startswith('item_'):
            numeric_id = numeric_id.split('_')[0]
        if not numeric_id:
            numeric_id = str(post_node.get('shortcode') or post_node.get('code') or "")
        if not numeric_id: continue

        cap_new   = get_caption(post_node)
        score_new = len(json.dumps(post_node)) + (50000 if cap_new else 0)

        if numeric_id not in unique_posts:
            unique_posts[numeric_id] = post_node
        else:
            existing_node = unique_posts[numeric_id]
            cap_old   = get_caption(existing_node)
            score_old = len(json.dumps(existing_node)) + (50000 if cap_old else 0)
            if score_new > score_old:
                unique_posts[numeric_id] = post_node

    posts_to_process = list(unique_posts.values())

    if not posts_to_process:
        safe_print("   ⚠️ No posts found in this file.")
    else:
        safe_print(f"   📦 Found {len(posts_to_process)} UNIQUE items (Processing max {ITEM_LIMIT} on {MAX_WORKERS} threads)")
        safe_print("   💡 HOTKEYS: [F] Skip file")
        _download_posts_batch(posts_to_process, out_dir, username, comments_map, media_source='raw')

    if isinstance(data, dict):
        fl = data.get('followingList', [])
        total_fl_users = sum(len(c.get('users', [])) for c in fl if isinstance(c, dict))
        if total_fl_users > 0:
            safe_print(f"\n   📋 [BONUS] 'followingList' mili ({total_fl_users} accounts) — processing...")
            fl_dir = os.path.join(out_dir, "following_data")
            os.makedirs(fl_dir, exist_ok=True)
            file_key = f"__embedded_following_{username}"
            module_following(data, fl_dir, username, file_key)

# ════════════════════════════════════════════════════════════════════
#  MODULE B ── CLEAN DATA PROCESSOR
# ════════════════════════════════════════════════════════════════════
def module_cleandata(data, out_dir, username):
    safe_print("   📋 [CLEAN] Extracting posts, highlights, active stories...")

    tag_active_stories_and_highlights(data)
    all_items = []

    for src_key in ('feedPosts', 'posts', 'scrapedPosts'):
        for p in data.get(src_key, []):
            p['source_type'] = 'Post'
            all_items.append(p)

    for hl in data.get('highlights', []):
        if 'items' in hl:
            title = sanitize_or(hl.get('title', ''), 'Highlight', 25)
            for it in hl['items']:
                it['_highlight_title'] = title
                it['_is_highlight']    = True
                it['product_type']     = 'story'
                all_items.append(it)
        else:
            hl['product_type'] = 'story'
            hl['_is_highlight'] = True
            all_items.append(hl)

    clean_stories = extract_active_stories_advanced(data)
    if clean_stories:
        all_items.extend(clean_stories)

    acc = data.get('accountInfo') or data.get('user')
    if isinstance(acc, dict):
        update_avatar_cache(acc)
        uname = acc.get('username') or acc.get('Username') or username
        av    = acc.get('profilePicUrl') or acc.get('profile_pic_url')
        if av: _avatar_cache.setdefault(uname, {'url': av, 'width': 150})

    if not all_items:
        safe_print("   ❌ No posts, highlights, or stories found in CleanData.")
        return

    safe_print(f"   📦 Found {len(all_items)} items (max {ITEM_LIMIT} on {MAX_WORKERS} threads)")
    safe_print("   💡 HOTKEYS: [F] Skip file")
    _download_posts_batch(all_items, out_dir, username, comments_map={}, media_source='clean')

# ════════════════════════════════════════════════════════════════════
#  MODULE C ── FOLLOWING LIST PROCESSOR (Multi-Threaded)
# ════════════════════════════════════════════════════════════════════
def _process_single_following_user(user, i, start_idx, recheck, csv_writer, csv_f, json_dir, pfps_dir, state, file_key):
    global shutdown_flag, skip_file_flag
    if shutdown_flag or skip_file_flag: return
    if i < start_idx and not recheck: return

    uname   = user.get('username')
    full    = user.get('full_name', '')
    pk_id   = str(user.get('pk_id') or user.get('pk') or user.get('id', ''))

    if not uname or not pk_id: return

    insta_url = f"https://www.instagram.com/{uname}/"
    hd_info   = user.get('hd_profile_pic_url_info', {})
    pfp_url   = (hd_info.get('url') if isinstance(hd_info, dict) else None) or user.get('profile_pic_url', '')
    bio       = user.get('biography', '')
    ext       = user.get('external_url', '')

    if not recheck:
        with csv_lock:
            csv_writer.writerow([insta_url, pk_id, uname, full, pfp_url, bio, ext])
            csv_f.flush()

    jpath = os.path.join(json_dir, f"@{uname}_{pk_id}.json")
    if not os.path.exists(jpath):
        try:
            with open(jpath, 'w', encoding='utf-8') as jf:
                json.dump(user, jf, indent=4)
            with state_lock: state[file_key]['json_saved'] += 1
        except Exception:
            pass

    with state_lock: download_av = state[file_key].get('download_avatars', True)

    if pfp_url and download_av:
        pfp_path = os.path.join(pfps_dir, f"@{uname}_avtar_{pk_id}.jpg")
        if os.path.exists(pfp_path):
            with state_lock: state[file_key]['pfps_skipped_exists'] += 1
        else:
            if download(pfp_url, pfp_path):
                safe_print(f"   Downloaded PFP: @{uname}")
                with state_lock: state[file_key]['pfps_downloaded'] += 1
            else:
                with state_lock: state[file_key]['pfps_failed'] += 1
    elif not recheck and not download_av:
        safe_print(f"   Extracted: @{uname}")

    with state_lock:
        if not recheck:
            if i + 1 > state[file_key]['processed_count']:
                state[file_key]['processed_count'] = i + 1

def module_following(data, out_dir, username, file_key):
    global skip_file_flag
    skip_file_flag = False

    safe_print(f"   📋 [FOLLOWING] Processing following list...")
    
    if isinstance(data, list):
        all_users = data
    else:
        chunks = data.get('followingList', [])
        if not chunks:
            safe_print("   [!] 'followingList' key nahi mili. Skipping.")
            return

        all_users = []
        for chunk in chunks:
            all_users.extend(chunk.get('users', []))

    total = len(all_users)
    safe_print(f"   [*] Total accounts: {total}")

    pfps_dir = os.path.join(out_dir, "pfps");       os.makedirs(pfps_dir, exist_ok=True)
    json_dir = os.path.join(out_dir, "users_data"); os.makedirs(json_dir, exist_ok=True)
    txt_path = os.path.join(out_dir, f"report_following_{username}.txt")
    csv_path = os.path.join(out_dir, f"following_accountlist_{username}.csv")

    state     = load_state()
    fstate    = state.get(file_key, {})
    start_idx = 0
    csv_mode  = 'w'
    recheck   = False

    if fstate:
        start_idx = fstate.get('processed_count', 0)
        if start_idx >= total:
            safe_print("   [✓] Already 100% done. Skipping.")
            return
        else:
            csv_mode = 'a'
            safe_print(f"   [*] RESUMING from account #{start_idx}...")

    dl_avatars    = True
    process_limit = total

    if not fstate:
        state[file_key] = {
            'processed_count': 0, 'download_avatars': dl_avatars,
            'process_limit': process_limit, 'pfps_downloaded': 0,
            'pfps_skipped_exists': 0, 'pfps_failed': 0,
            'json_saved': 0, 'start_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_state(state)

    safe_print(f"   [i] MODE: STRAIGHT AUTO — Processing {process_limit} accounts on {MAX_WORKERS} threads...\n")

    with open(csv_path, mode=csv_mode, newline='', encoding='utf-8') as csv_f:
        writer = csv.writer(csv_f)
        if csv_mode == 'w':
            writer.writerow(['Instagram URL','PK ID','Username','Full Name','Avatar Link','Bio','External URL'])

        users_to_process = all_users[:process_limit]

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = []
            for i, user in enumerate(users_to_process):
                futures.append(executor.submit(
                    _process_single_following_user,
                    user, i, start_idx, recheck, writer, csv_f, json_dir, pfps_dir, state, file_key))

            while futures:
                if shutdown_flag: break
                key = _check_hotkey()
                if key == 'f':
                    safe_print("\n   ⏭️ [F] Following list skipped by user.")
                    break
                futures = [f for f in futures if not f.done()]
                with state_lock:
                    save_state(state)
                    _write_txt_report(txt_path, file_key, out_dir, state[file_key], total)
                import time; time.sleep(0.5)

    save_state(state)
    _write_txt_report(txt_path, file_key, out_dir, state[file_key], total)
    safe_print(f"\n   [✓] Following done for: {file_key}")

# ════════════════════════════════════════════════════════════════════
#  MODULE D ── SUGGESTED USERS PROCESSOR
# ════════════════════════════════════════════════════════════════════
def module_suggested(data, out_dir, source_filename):
    safe_print("   📋 [SUGGESTED] Extracting suggested accounts...")
    try:
        if isinstance(data, list):
            target_user = data[0]['data']['user']['reel']['user']
            edges       = data[0]['data']['user']['edge_chaining']['edges']
        else:
            target_user = data.get('data', {}).get('user', {}).get('reel', {}).get('user', {})
            edges       = data.get('data', {}).get('user', {}).get('edge_chaining', {}).get('edges', [])
    except (KeyError, IndexError, TypeError) as e:
        safe_print(f"   ❌ Unsupported structure for suggested: {e}")
        return

    t_uname  = target_user.get('username', 'unknown')
    t_pk     = target_user.get('id', 'unknown')
    total    = len(edges)
    date_s   = datetime.now().strftime("%d %B %Y")
    txt_path = os.path.join(out_dir, f"{t_uname}_{t_pk}_suggested.txt")

    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("             INSTAGRAM SUGGESTED ACCOUNTS REPORT\n")
        f.write("=" * 80 + "\n")
        f.write(f"Target Account : {t_uname} (PK: {t_pk})\n")
        f.write(f"Total Accounts : {total}\n")
        f.write(f"Date Extracted : {date_s}\n")
        f.write("=" * 80 + "\n\n")
        for idx, edge in enumerate(edges, 1):
            n     = edge.get('node', {})
            pk    = n.get('id', 'N/A')
            uname = n.get('username', 'N/A')
            fname = n.get('full_name', '') or 'N/A'
            url   = f"https://www.instagram.com/{uname}"
            f.write(f"[{idx:02d}] PK ID    : {pk}\n")
            f.write(f"     Creator : {fname} (@{uname})\n")
            f.write(f"     URL     : {url}\n")
            f.write("-" * 80 + "\n")

    safe_print(f"   ✅ Suggested report saved: {os.path.basename(txt_path)}")

# ════════════════════════════════════════════════════════════════════
#  MODULE E ── TAGGED POSTS PROCESSOR
# ════════════════════════════════════════════════════════════════════
def module_tagged(data, out_dir, username):
    safe_print("   📋 [TAGGED] Extracting tagged posts...")
    edges = (data.get('data', {})
                 .get('xdt_api__v1__usertags__user_id__feed_connection', {})
                 .get('edges', []))

    if not edges:
        safe_print("   ⚠️ No tagged post edges found.")
        return

    date_s   = datetime.now().strftime("%d %B %Y")
    grouped  = {}
    csv_rows = []
    report   = []
    profiles = set()

    for edge in edges:
        node      = edge.get('node', {})
        code      = node.get('code', '')
        post_url  = f"https://www.instagram.com/p/{code}/" if code else "N/A"
        owner     = node.get('user', {})
        poster_u  = owner.get('username', 'N/A')
        poster_pk = owner.get('pk', 'N/A')
        prof_url  = f"https://www.instagram.com/{poster_u}/" if poster_u != 'N/A' else "N/A"

        cap_obj  = node.get('caption', {})
        cap_text = (cap_obj.get('text', '') if isinstance(cap_obj, dict) else '').replace('\n', ' ')[:80]

        if prof_url != "N/A": profiles.add(prof_url)
        grouped.setdefault(poster_pk, {'username': poster_u, 'posts': []})['posts'].append(node)
        if post_url != "N/A": csv_rows.append([post_url, prof_url, poster_u, poster_pk])
        report.append({'poster': poster_u, 'pk': poster_pk, 'url': post_url, 'caption': cap_text})

    json_dir = os.path.join(out_dir, "Rich_JSON_Files")
    os.makedirs(json_dir, exist_ok=True)
    for pk, val in grouped.items():
        fname = f"@{val['username']}_{pk}_tagged_{username}.json"
        with open(os.path.join(json_dir, fname), 'w', encoding='utf-8') as f:
            json.dump(val['posts'], f, indent=4, ensure_ascii=False)

    csv_path = os.path.join(out_dir, f"{username}_Links.csv")
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(["Post URL","Profile URL","Poster Username","Poster PK ID"])
        w.writerows(csv_rows)

    txt_path = os.path.join(out_dir, f"{username}_Report.txt")
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("             ENTERPRISE INSTAGRAM TAGGED POSTS REPORT\n")
        f.write("=" * 80 + "\n")
        f.write(f"Target Account : {username}\n")
        f.write(f"Total Posts    : {len(csv_rows)}\n")
        f.write(f"Unique Taggers : {len(profiles)}\n")
        f.write(f"Date Extracted : {date_s}\n")
        f.write("=" * 80 + "\n\n")
        for i, d in enumerate(report, 1):
            f.write(f"[{i:03d}] POSTER  : @{d['poster']} (PK: {d['pk']})\n")
            f.write(f"      POST URL: {d['url']}\n")
            f.write(f"      CAPTION : {d['caption']}...\n")
            f.write("-" * 80 + "\n")

    safe_print(f"   ✅ Tagged posts done — {len(csv_rows)} posts, {len(profiles)} taggers.")

# ════════════════════════════════════════════════════════════════════
#  SECTION 10 ── SMART FILE ROUTER
# ════════════════════════════════════════════════════════════════════
def _detect_mode(filepath, data):
    fname = os.path.basename(filepath).lower()
    if isinstance(data, dict):
        has_feed    = bool(data.get('feedPosts'))
        has_stories = bool(data.get('activeStories'))
        has_fl      = bool(data.get('followingList'))
        has_tags    = 'xdt_api__v1__usertags__user_id__feed_connection' in str(data)[:300]

        if has_feed or has_stories:
            if 'cleandata' in fname or 'clean' in fname: return 'cleandata'
            return 'rawdata'

        if has_fl:
            for chunk in data['followingList']:
                if isinstance(chunk, dict) and chunk.get('users'): return 'following'

        if has_tags: return 'tagged'

    if 'tagged'    in fname or '_all_tagged' in fname: return 'tagged'
    if 'suggested' in fname:                           return 'suggested'
    if 'cleandata' in fname or 'clean' in fname:       return 'cleandata'
    if 'following' in fname or 'followers' in fname:   return 'following'

    if isinstance(data, list) and len(data) > 0:
        try:
            if isinstance(data[0], dict):
                if 'edge_chaining' in str(data[0].get('data', {})):
                    return 'suggested'
                if 'username' in data[0]: 
                    return 'following'
        except Exception:
            pass

    return 'rawdata'

def _get_username(filepath, data):
    if isinstance(data, dict):
        acc = data.get('accountInfo') or data.get('user')
        if isinstance(acc, dict):
            u = acc.get('username') or acc.get('Username')
            if u: return u

    parts = os.path.basename(filepath).replace('.json', '').split('_')
    for p in parts:
        if p and not p.isdigit() and len(p) > 2 and p.lower() not in (
            'ig','rawdata','cleandata','fast','full','following',
            'highlights','stories','posts','tagged','suggested'):
            return p
    return 'unknown_user'

def process_file(json_path):
    global skip_file_flag
    if shutdown_flag: return
    skip_file_flag = False

    safe_print(f"\n{'═'*65}")
    safe_print(f"  ✨ FILE: {os.path.basename(json_path)}")
    safe_print(f"{'═'*65}")
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError:
        safe_print(f"  ❌ Invalid JSON — skipping: {os.path.basename(json_path)}")
        return

    mode     = _detect_mode(json_path, data)
    username = _get_username(json_path, data)

    raw_base = os.path.basename(json_path).replace('.json', '')
    base     = sanitize_or(raw_base, raw_base, 55)
    out_dir  = os.path.join(OUTPUT_FOLDER, f"EXTRACTED_{base}")
    os.makedirs(out_dir, exist_ok=True)

    safe_print(f"  👤 Username : @{username}")
    safe_print(f"  📂 Out Dir  : .../{BATCH_FOLDER_NAME}/EXTRACTED_{base}")
    safe_print(f"  🔍 Mode     : {mode.upper()}")

    if   mode == 'following': module_following(data, out_dir, username, os.path.basename(json_path))
    elif mode == 'tagged':    module_tagged(data, out_dir, username)
    elif mode == 'suggested': module_suggested(data, out_dir, os.path.basename(json_path))
    elif mode == 'cleandata': module_cleandata(data, out_dir, username)
    else:                     module_rawdata(data, out_dir, username)

    if not shutdown_flag:
        safe_print(f"\n  ✅ Done: {os.path.basename(json_path)}")

# ════════════════════════════════════════════════════════════════════
#  SECTION 11 ── ENTRY POINT
# ════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    safe_print("╔══════════════════════════════════════════════════════════════╗")
    safe_print("║   UNIVERSAL INSTAGRAM EXTRACTOR — PRO AUTO-BATCH EDITION     ║")
    safe_print("║   Modules: RawData | CleanData | Following | Suggested | Tag ║")
    safe_print("╚══════════════════════════════════════════════════════════════╝\n")

    # STEP 1: Loose JSON files ko datasets folder mein move karo
    organize_input_files()

    # STEP 2: datasets folder se saari JSON files uthao
    all_files = sorted(glob.glob(os.path.join(INPUT_FOLDER, '**', '*.json'), recursive=True))
    all_files = [f for f in all_files if 'resume_state' not in f and 'EXTRACTED_' not in f]

    if not all_files:
        safe_print(f"  ❌ Koi JSON file nahi mili in: {INPUT_FOLDER}")
        safe_print(f"     JSON files yahan rakhein: {INPUT_FOLDER}")
        safe_print(f"     Ya uni.py ke sath wali directory mein: {SCRIPT_DIR}")
        sys.exit(0)

    safe_print(f"  📁 Input Folder  : {INPUT_FOLDER}")
    safe_print(f"  📂 Output Batch  : {OUTPUT_FOLDER}")
    safe_print(f"  📥 Download Media: {DOWNLOAD_MEDIA}")
    safe_print(f"  🔢 Item Limit    : {ITEM_LIMIT}")
    safe_print(f"  🔢 Threads       : {MAX_WORKERS}")
    safe_print(f"  ⌨️  HOTKEYS (Win) : [F] Skip File\n")
    safe_print(f"  🗂️  Found {len(all_files)} JSON file(s):\n")
    for f in all_files:
        safe_print(f"      • {os.path.basename(f)}")
    safe_print()

    # STEP 3: Processing
    for f in all_files:
        if shutdown_flag: break
        process_file(f)

    if shutdown_flag:
        safe_print("\n🛑 Script stopped manually. Aapka sab data mehfooz hai.")
    else:
        safe_print(f"\n🏁 ALL FILES PROCESSED!")
        safe_print(f"📂 Data yahan save hua: {OUTPUT_FOLDER}")