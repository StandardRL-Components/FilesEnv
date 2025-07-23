#!/usr/bin/env python3
"""
generate_trees.py

Generates realistic-looking UNIX-style home directory trees for training agents,
using external word lists (created via LLM prompts) for plausible file names, sizes,
and detailed music albums with track listings.

Usage:
    generate_trees.py <count> <output_dir>
    - count=0: print one tree to stdout
    - count>0: generate <count> trees as .txt files under <output_dir> (won't overwrite existing)
"""

import os
import sys
import uuid
import random
import argparse
import json
from datetime import datetime

# ---------- Helpers for size handling ----------

def parse_size(size_str):
    """Return a size string or default to '0B'."""
    return size_str if size_str else '0B'


def generate_dummy_size(name):
    """Generate a plausible size based on file extension."""
    ext = os.path.splitext(name)[1].lower()
    if ext in ('.pdf', '.docx', '.xlsx'):
        return f"{random.uniform(0.1, 5):.1f}MB"
    if ext in ('.txt', '.md', '.css', '.json', '.ini', '.sh'):
        return f"{random.uniform(1, 100):.0f}KB"
    if ext in ('.jpg', '.jpeg', '.png'):
        return f"{random.uniform(0.05, 5):.1f}MB"
    if ext in ('.mp3',):
        return f"{random.uniform(3, 10):.1f}MB"
    if ext in ('.mp4', '.avi', '.mkv'):
        size = random.uniform(10, 2000)
        return f"{size/1024:.1f}GB" if size > 1024 else f"{size:.1f}MB"
    if ext in ('.zip', '.tar.gz', '.dmg', '.exe', '.apk'):
        return f"{random.uniform(1, 500):.1f}MB"
    return f"{random.uniform(14, 500):.1f}B"

# ---------- Load external word lists ----------

def load_word_list(category):
    """
    Loads (name, size) tuples from word_lists/{category}-words.txt.
    Lines should be: filename.ext, size (e.g. report.pdf, 1.2MB).
    """
    path = os.path.join('word_lists', f'{category}-words.txt')
    entries = []
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if ',' in line:
                    name, size = line.rsplit(',', 1)
                    entries.append((name.strip(), size.strip()))
                else:
                    entries.append((line.strip(), None))
    except FileNotFoundError:
        print(f"Warning: word list for '{category}' not found at {path}", file=sys.stderr)
    return entries


def load_music_albums():
    """
    Loads a JSON array from word_lists/Music-albums.json.
    Each element should be an object: {"album": str, "songs": [{"title":str,"size":str}, ...]}.
    """
    path = os.path.join('word_lists', 'Music-albums.json')
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Warning: Music albums JSON not found at {path}", file=sys.stderr)
        return []

# Load all lists
DOCUMENT_WORDS     = load_word_list('Documents')
DOWNLOAD_WORDS     = load_word_list('Downloads')
PICTURE_WORDS      = load_word_list('Pictures')
VIDEO_WORDS        = load_word_list('Videos')
MOVIE_WORDS        = load_word_list('Movies')
EBOOK_WORDS        = load_word_list('EBooks')
PRESENTATION_WORDS = load_word_list('Presentations')
SCRIPT_WORDS       = load_word_list('Scripts')
DESKTOP_WORDS      = load_word_list('Desktop')
MUSIC_ALBUMS       = load_music_albums()

# Static pools for config & SSH
CONFIG_APPS = {
    'vscode': ['settings.json', 'keybindings.json', 'extensions.json'],
    'firefox': ['profiles.ini', 'prefs.js'],
    'git': ['config', 'ignore']
}
SSH_FILES = ['id_rsa', 'id_rsa.pub', 'known_hosts', 'config']

# ---------- Generation functions ----------

def gen_documents():
    tree = {}
    # Flat list of document files
    count = random.randint(5, min(len(DOCUMENT_WORDS), 20))
    picks = random.sample(DOCUMENT_WORDS, k=count)
    for name, size in picks:
        tree[name] = parse_size(size) if size else generate_dummy_size(name)
    return tree


def gen_downloads():
    tree = {}
    count = random.randint(5, min(len(DOWNLOAD_WORDS), 15))
    picks = random.sample(DOWNLOAD_WORDS, k=count)
    for name, size in picks:
        tree[name] = parse_size(size) if size else generate_dummy_size(name)
    return tree


def gen_music():
    tree = {}
    if MUSIC_ALBUMS:
        albums = random.sample(
            MUSIC_ALBUMS,
            k=random.randint(1, min(5, len(MUSIC_ALBUMS)))
        )
        ext = random.choice(['.mp3', '.wav', '.m4a'])
        for alb in albums:
            title = alb['album']
            songs = alb.get('songs', [])
            if not songs:
                continue

            # compute a valid lower bound
            max_tracks = len(songs)              # up to all
            # or, if you really want at least 5 whenever possible:
            lower = min(5, len(songs))
            picks = random.sample(songs, k=random.randint(lower, max_tracks))

            sub = {}
            for s in picks:
                fname = s['title'].replace(' ', '_') + ext
                size = s.get('size')
                sub[fname] = parse_size(size) if size else generate_dummy_size(fname)
            tree[title] = sub
    return tree


def gen_pictures():
    tree = {}
    # top-level picture files
    top_count = random.randint(5, min(len(PICTURE_WORDS), 50))
    top_picks = random.sample(PICTURE_WORDS, k=top_count)
    for name, size in top_picks:
        tree[name] = parse_size(size) if size else generate_dummy_size(name)
    return tree


def gen_videos_or_movies(kind):
    tree = {}
    pool = VIDEO_WORDS if kind == 'Videos' else MOVIE_WORDS
    count = random.randint(3, min(len(pool), 10))
    picks = random.sample(pool, k=count)
    for name, size in picks:
        tree[name] = parse_size(size) if size else generate_dummy_size(name)
    return tree


def gen_ebooks():
    tree = {}
    count = random.randint(1, min(len(EBOOK_WORDS), 5))
    picks = random.sample(EBOOK_WORDS, k=count)
    for name, size in picks:
        tree[name] = parse_size(size) if size else generate_dummy_size(name)
    return tree


def gen_presentations():
    tree = {}
    count = random.randint(1, min(len(PRESENTATION_WORDS), 5))
    picks = random.sample(PRESENTATION_WORDS, k=count)
    for name, size in picks:
        tree[name] = parse_size(size) if size else generate_dummy_size(name)
    return tree


def gen_scripts():
    tree = {}
    count = random.randint(1, min(len(SCRIPT_WORDS), 10))
    picks = random.sample(SCRIPT_WORDS, k=count)
    for name, size in picks:
        tree[name] = parse_size(size) if size else generate_dummy_size(name)
    return tree


def gen_desktop():
    tree = {}
    count = random.randint(1, min(len(DESKTOP_WORDS), 10))
    if DESKTOP_WORDS:
        picks = random.sample(DESKTOP_WORDS, k=count)
    else:
        default = ['todo.txt', 'startup.sh', 'readme.md', 'screenshot.png']
        picks = [(name, None) for name in random.sample(default, k=count)]
    for name, size in picks:
        tree[name] = parse_size(size) if size else generate_dummy_size(name)
    return tree


def gen_config():
    tree = {}
    for app, files in random.sample(list(CONFIG_APPS.items()), k=random.randint(1, len(CONFIG_APPS))):
        for f in files:
            tree[f".config/{app}/{f}"] = generate_dummy_size(f)
    return tree


def gen_ssh():
    tree = {}
    for f in SSH_FILES:
        tree[f".ssh/{f}"] = generate_dummy_size(f)
    return tree


def build_one_tree():
    gens = {
        'Documents': gen_documents,
        'Downloads': gen_downloads,
        'Desktop': gen_desktop,
        'Music': gen_music,
        'Pictures': gen_pictures,
        'Videos': lambda: gen_videos_or_movies('Videos'),
        'Movies': lambda: gen_videos_or_movies('Movies'),
        'EBooks': gen_ebooks,
        'Presentations': gen_presentations,
        'Scripts': gen_scripts,
        'SSH': gen_ssh
    }

    mandatory = ['Documents', 'Downloads', 'Desktop']
    optional = [k for k in gens if k not in mandatory]
    chosen = set(mandatory)
    while len(chosen) < random.randint(6, 9):
        pick = random.choice(optional)
        if pick in ('Videos', 'Movies') and any(v in chosen for v in ('Videos', 'Movies')):
            continue
        chosen.add(pick)

    tree = {}
    for key in chosen:
        subtree = gens[key]()
        # flatten nested paths for Config/SSH
        if '\n' not in key and key in ('Config','SSH'):
            for path, size in subtree.items():
                parts = path.split('/')
                d = tree
                for p in parts[:-1]:
                    d = d.setdefault(p, {})
                d[parts[-1]] = size
        else:
            tree[key] = subtree
    return tree


def render_tree(tree, indent=0):
    lines = []
    for name, node in sorted(tree.items()):
        if isinstance(node, dict):
            lines.append('  ' * indent + f"{name}/")
            lines.extend(render_tree(node, indent+1))
        else:
            lines.append('  ' * indent + f"{name} ({node})")
    return lines


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('count', type=int, help="0=print one tree; >0=generate that many files")
    parser.add_argument('output', nargs='?', help="Output directory for tree files")
    args = parser.parse_args()

    if args.count > 0:
        if not args.output:
            print("Error: must specify <output_dir> when count>0", file=sys.stderr)
            sys.exit(1)
        os.makedirs(args.output, exist_ok=True)
        for _ in range(args.count):
            tree = build_one_tree()
            text = "\n".join(render_tree(tree))
            fname = os.path.join(
                args.output,
                f"home_tree_{datetime.now():%Y%m%d}_{uuid.uuid4().hex[:8]}.txt"
            )
            with open(fname, 'w', encoding='utf-8') as f:
                f.write(text)
        print(f"Generated {args.count} trees in '{args.output}'")
    else:
        print("\n".join(render_tree(build_one_tree())))

if __name__ == '__main__':
    main()
