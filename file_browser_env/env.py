from threading import Thread, Condition
import docker
from docker.errors import NotFound
from ipaddress import ip_network
import os
import tempfile
import shutil
import threading
import subprocess
import yaml
import uuid
from vncdotool import api
import io
import numpy as np
from pathlib import Path
import json
import pkg_resources
import gymnasium as gym
from gymnasium import spaces
import random
from urllib.parse import urlparse

import string
import os
import json
import threading

import time

import re


class FBEnvironmentException(Exception):
    """Exception raised when maximum number of environments are created."""
    pass

class FBEnvironment:
    _docker_client = docker.from_env()
    _network_name = None
    _available_ips = []
    _lock = threading.Lock()  # For thread safety when managing IPs
    _initialized = False
    _subnet = None
    
    # Class-level dictionary to map IP addresses to instances
    _instances = {}

    # Create Docker network and IP pool on the first instantiation
    @classmethod
    def _initialize_network(cls, ip_range="172.20.0.0/24"):
        """Initialize Docker network and populate available IP list."""
        try:
            print(f"Loading network {cls._network_name}")
            cls._docker_client.networks.get(cls._network_name)
        except NotFound:
            print(f"Not found. Making new network {cls._network_name}")
            # Create the network with a specified subnet
            cls._docker_client.networks.create(
                cls._network_name,
                driver="bridge",
                ipam=docker.types.IPAMConfig(
                    pool_configs=[docker.types.IPAMPool(subnet=ip_range)]
                )
            )

        # Generate list of available IPs from subnet, excluding gateway (.1)
        cls._available_ips = [str(ip) for ip in ip_network(ip_range).hosts()][1:]


    @classmethod
    def _cleanup_existing_containers(cls):
        """Stop and remove all containers created by previous runs of this script."""
        containers = cls._docker_client.containers.list(
            all=True,
            filters={"label": f"created_by=FBEnvironment{FBEnvironment._subnet}"}
        )
        for container in containers:
            try:
                container.stop()
                container.remove()
                print(f"Removed container {container.id}")
            except Exception as e:
                print(f"Failed to remove container {container.id}: {e}")

    def __init__(self, height, width, templates=None, subnet=20, send_pipe=None, recv_pipe=None, child_mode=False, static_ip=None, onNavigate=None, username="user"):
        """Initialize the environment, start Docker container, and assign an IP."""

        compose_file = Path(pkg_resources.resource_filename('browser_env', 'compose-fb.yaml'))
        
        self.subnet = subnet
        self._log = ""


        # Perform one-time cleanup of existing containers
        if not FBEnvironment._initialized:
            FBEnvironment._subnet = self.subnet
            FBEnvironment._network_name = f"browser_environment_network_{self.subnet}"
            if not child_mode:
                FBEnvironment._cleanup_existing_containers()
                FBEnvironment._initialize_network(ip_range=f"172.{self.subnet}.0.0/24")
            
            FBEnvironment._initialized = True

        if static_ip is None:
            # Acquire lock to safely assign IP
            with FBEnvironment._lock:
                if not FBEnvironment._available_ips:
                    raise FBEnvironmentException("Maximum number of environments created")
                self.ip_address = FBEnvironment._available_ips.pop(0)
        else:
            self.ip_address = static_ip

        # Store the instance in the class-level dictionary
        FBEnvironment._instances[self.ip_address] = self

        # 1) Align container user to your host user
        self.uid = os.getuid()
        self.gid = os.getgid()

        # 2) Let 'username' (default 'user') drive the home-folder name
        #    but DO NOT change UID/GID—they stay host values.
        self.username       = username
        self.container_home = f"/home/{self.username}"

        #  A) Create a fresh host‐side folder and populate it:
        self.homedir = tempfile.mkdtemp(prefix="fb_env_")
        self.templates = os.path.abspath(templates) if (templates and os.path.isdir(templates)) else None
        self._populate_random_files(self.homedir, self.templates)

        self.width = width
        self.height = height

        self.isMouseDown = False

        self.vnc_client = None

        self.TOOLBAR_MARGIN = 0

        # Generate a unique project name to isolate this instance
        self.project_name = f"browser_env_{uuid.uuid4().hex[:8]}"

        # Create the FIFO for navigation events
        self.pipe_path = os.path.join(self.homedir, ".hidden")
        try:
            os.mkfifo(self.pipe_path)
        except FileExistsError:
            pass

        # Store optional callback
        self.onNavigate = onNavigate

        # Start background listener thread
        self._stop_pipe = threading.Event()
        t = threading.Thread(target=self._pipe_listener, daemon=True)
        t.start()

        # Modify the compose file to set the correct volumes, IP address, and exposed ports
        with open(compose_file, "r") as file:
            self.compose_data = yaml.safe_load(file)
    
        self._fetch_and_bind_extra_themes()

        self.compose_data['version'] = '3.7'

        # Apply environment-specific configurations to the compose file data
        self.compose_data['services']['fb_service'].update({
            "networks": {
                FBEnvironment._network_name: {
                    "ipv4_address": self.ip_address
                }
            },
            "volumes": [
                f"{self.homedir}:{self.container_home}:rw"
            ],
            "expose": ["5900"],  # Expose port 5901 for VNC
            "labels": {  # Add label to identify containers created by this script
                "created_by": f"FBEnvironment{self.subnet}"
            }
        })

        # 1) Randomly hide or show sidebar
        self.hide_sidebar = random.choice(["true","false"])
        self._lastKnownViewMode = random.choice(["icon-view","list-view"])

        # 2) Pick 2–4 random standard folders for bookmarks, but only those that actually exist
        options = ["Documents", "Desktop", "Downloads", "Music", "Pictures", "Videos", "Templates"]
        # filter to real directories under home
        existing = [
            d for d in options
            if os.path.isdir(os.path.join(self.homedir, d))
        ]
        if existing:
            count  = random.randint(2, min(4, len(existing)))
            chosen = random.sample(existing, count)
        else:
            chosen = []
        bm_str = ",".join(chosen)

        # 3) Inject into the container’s env
        self.compose_data['services']['fb_service']['environment'].update({
            "VNC_PASSWORD":     "12345",
            "USER_ID":          self.uid,
            "GROUP_ID":         self.gid,
            "USER_NAME":        self.username,
            "KEEP_APP_RUNNING": "1",
            "DISPLAY_WIDTH":    self.width,
            "DISPLAY_HEIGHT":   self.TOOLBAR_MARGIN + self.height,
            # new for random sidebar/bookmarks:
            "SIDEBAR_HIDDEN":   self.hide_sidebar,
            "ICONVIEW":   "true" if self._lastKnownViewMode == "icon-view" else "false",
            "BOOKMARKS":        bm_str,
        })

        self.compose_data['networks'] = {}
        self.compose_data['networks'][FBEnvironment._network_name] = {
            'external': True
        }
        
        
        # Write modified compose data to a temporary file for this instance
        self.modified_compose_file = tempfile.NamedTemporaryFile(delete=False, suffix=".yaml")
        with open(self.modified_compose_file.name, 'w') as file:
            yaml.dump(self.compose_data, file)

        self.modified_compose_file.close()
        # Start the container with the modified compose file and unique project name
        try:
            subprocess.run(
                ["docker-compose", "-f", self.modified_compose_file.name, "up", "-d"],
                check=True,
                env=dict(os.environ, COMPOSE_PROJECT_NAME=self.project_name)
            )
        except subprocess.CalledProcessError as e:
            # Return IP to pool and clean up temp dir if container fails to start
            with FBEnvironment._lock:
                FBEnvironment._available_ips.append(self.ip_address)
                
            # Remove the instance from the class-level dictionary
            FBEnvironment._instances.pop(self.ip_address, None)

            os.remove(self.modified_compose_file.name)
            raise e
        
        self._latest_screen = None
        self._known_mouse = None
    
        self._lastKnownPath = "/home/user"
        if self.onNavigate:
            self.onNavigate("", "icon")

        self._generate_instruction()

    def update_sidebar_bookmarks(self, bookmarks):
        """
        Update the Nautilus sidebar “Bookmarks” to the given list, in real time.

        `bookmarks` should be a list of (relative_path, title) tuples,
        e.g. [("Documents/Work", "Work"), ("Pictures", "Photos")].

        This writes both ~/.config/gtk-3.0/bookmarks and ~/.gtk-bookmarks
        inside the container’s home mount, then does `nautilus -q` to reload.
        """
        import os, io

        # 1) Build the two bookmark files under homedir
        gtk_cfg = os.path.join(self.homedir, ".config", "gtk-3.0")
        os.makedirs(gtk_cfg, exist_ok=True)
        lines = []
        for relpath, title in bookmarks:
            uri = f"file://{self.container_home}/{relpath}"
            lines.append(f"{uri}\t{title}")

        # write gtk-3.0/bookmarks
        with open(os.path.join(gtk_cfg, "bookmarks"), "w") as f:
            f.write("\n".join(lines))

        # write the legacy ~/.gtk-bookmarks
        with open(os.path.join(self.homedir, ".gtk-bookmarks"), "w") as f:
            f.write("\n".join(lines))

        # 2) Tell Nautilus to reload by quitting—it will restart via your loop
        container = FBEnvironment._docker_client.containers.get(
            f"{self.project_name}_fb_service_1"
        )
        # `nautilus -q` cleanly quits, your startapp.sh will bring it back
        container.exec_run(["nautilus", "-q"], user=f"{self.uid}:{self.gid}")

    def reset(self):
        """
        Wipe & re-populate home; then randomly re-theme Nautilus,
        re-seed the sidebar and pick view/sidebar preferences.
        """
        # --- 1) wipe out everything under homedir except our pipe
        for name in os.listdir(self.homedir):
            if name == os.path.basename(self.pipe_path):
                continue
            path = os.path.join(self.homedir, name)
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
            except Exception:
                pass

        # --- 2) rebuild the random tree & pick a new task
        self._populate_random_files(self.homedir, self.templates)
        self._generate_instruction()

        # --- 3) pick sidebar/view/bookmarks exactly as before
        # --- 3) pick sidebar/bookmarks/view preferences
        self.hide_sidebar      = random.choice(["true","false"])
        self._lastKnownViewMode = random.choice(["icon-view","list-view"])

        opts     = ["Documents","Desktop","Downloads","Music","Pictures","Videos","Templates"]
        existing = [d for d in opts if os.path.isdir(os.path.join(self.homedir, d))]
        chosen   = random.sample(existing, k=random.randint(2, min(4, len(existing)))) if existing else []
        # build bookmark lines
        # ─── seed bookmarks into the container’s XDG_CONFIG_HOME ─────────────
        bk_csv = ",".join(chosen)
        shell = f'''
export XDG_CONFIG_HOME=/tmp/xdg-config

# drop the old bookmarks
rm -f "$XDG_CONFIG_HOME/gtk-3.0/bookmarks"

# re-create the directory
mkdir -p "$XDG_CONFIG_HOME/gtk-3.0"

# seed in your new list
IFS=',' read -ra BMLIST <<< "{bk_csv}"
for d in "${{BMLIST[@]}}"; do
  echo "file://$HOME/$d    $d" >> "$XDG_CONFIG_HOME/gtk-3.0/bookmarks"
done
'''

        # --- 4) pick GTK and icon themes from our extra-themes dir
        base_extra = os.path.expanduser("~/.nautilus_extra_themes")
        try:
            gtk_theme  = random.choice(os.listdir(os.path.join(base_extra, "themes")))
        except Exception:
            gtk_theme = ""
        try:
            icon_theme = random.choice(os.listdir(os.path.join(base_extra, "icons")))
        except Exception:
            icon_theme = ""

        # --- 5) kill & re-launch Nautilus under new env + gsettings
        container = FBEnvironment._docker_client.containers.get(
            f"{self.project_name}_fb_service_1"
        )
        # quit Nautilus
        
        res = container.exec_run(
            ["bash", "-lc", shell],
            user=f"{self.uid}:{self.gid}"
        )

        container.exec_run(["pkill", "-f", "nautilus"], user=f"{self.uid}:{self.gid}")

        cmd = [
            # 1) re-export your XDG roots so Nautilus reads from /tmp/xdg-*
            'export XDG_CONFIG_HOME=/tmp/xdg-config',
            'export XDG_CACHE_HOME=/tmp/xdg-cache',
            'export XDG_STATE_HOME=/tmp/xdg-state',
            'export XDG_DATA_HOME=/tmp/xdg-data',
            'export XDG_RUNTIME_DIR=/tmp/xdg-runtime',

            # 2) re-export the themes
            f'export GTK_THEME="{gtk_theme}"',
            f'export ICON_THEME="{icon_theme}"',

            # 3) toggle sidebar & default view
            f'gsettings set org.gnome.nautilus.window-state start-with-sidebar {self.hide_sidebar}',
            f'gsettings set org.gnome.nautilus.preferences default-folder-viewer {self._lastKnownViewMode}',

            # 4) finally start Nautilus pointed at the real home
            f'exec nautilus --no-desktop "{self.container_home}"'
        ]
        bash_invocation = " && ".join(cmd)

        container.exec_run(
            ["bash", "-lc", bash_invocation],
            user=f"{self.uid}:{self.gid}",
            detach=True
        )

        # small pause and warm up
        time.sleep(0.5)
        self.getScreen()

    def _pipe_listener(self):
        """Continuously read JSON lines from the FIFO and dispatch onNavigate."""
        with open(self.pipe_path, "r") as fifo:
            while not self._stop_pipe.is_set():
                line = fifo.readline()
                if not line:
                    # EOF → reopen
                    time.sleep(0.1)
                    continue
                try:
                    data = json.loads(line.strip())

                    self._log = f"{self._log} \n {time.time()}: {line.strip()}"

                    latestPath = data.get("path", None)
                    latestViewMode = data.get("view", None)

                    if (self._lastKnownPath != latestPath) or (self._lastKnownViewMode != latestViewMode):
                        self._lastKnownPath = latestPath
                        self._lastKnownViewMode = latestViewMode

                        prefix = self.container_home
                        if latestPath.startswith(prefix):
                            rel = latestPath[len(prefix):] or "/"

                            # callback signature: onNavigate(path, view)
                            if self.onNavigate:
                                self.onNavigate(rel, latestViewMode)

                        
                except json.JSONDecodeError:
                    pass


    def _fetch_and_bind_extra_themes(self):
        """
        Ensure at least 10 GTK and 10 icon themes are available by
        cloning them into ~/.nautilus_extra_themes/(themes|icons),
        then bind-mounting into the container.
        """
        import os, subprocess

        base_dir   = os.path.expanduser("~/.nautilus_extra_themes")
        themes_dir = os.path.join(base_dir, "themes")
        icons_dir  = os.path.join(base_dir, "icons")
        os.makedirs(themes_dir, exist_ok=True)
        os.makedirs(icons_dir,  exist_ok=True)

        # A small curated list of popular GTK themes
        gtk_repos = [
            ("Arc",      "https://github.com/horst3180/arc-theme.git"),
            ("Adapta",   "https://github.com/adapta-project/adapta-gtk-theme.git"),
            ("Materia",  "https://github.com/nana-4/materia-theme.git"),
            ("Pop",      "https://github.com/pop-os/gtk-theme.git"),
            ("Canta",    "https://github.com/vinceliuice/Canta-theme.git"),
            ("Nord",     "https://github.com/nordtheme/nord.git"),
            ("Dracula",  "https://github.com/dracula/gtk.git"),
            ("FlatRemix","https://github.com/daniruiz/flat-remix-gtk.git"),
            ("WhiteSur", "https://github.com/vinceliuice/WhiteSur-gtk-theme.git"),
        ]

        icon_repos = [
            ("Papirus",      "https://github.com/PapirusDevelopmentTeam/papirus-icon-theme.git"),
            ("Moka",         "https://github.com/snwh/Moka-icon-theme.git"),
            ("Numix",        "https://github.com/numixproject/numix-icon-theme.git"),
            ("FlatRemix",    "https://github.com/daniruiz/flat-remix.git"),
            ("La-Capitaine", "https://github.com/keeferrourke/la-capitaine-icon-theme.git"),
            ("Tela",         "https://github.com/vinceliuice/Tela-icon-theme.git"),
            # Papirus variants all live in the main Papirus repo (it contains Papirus, Papirus-Dark, Papirus-Light, etc.)
        ]

        # Clone each if missing
        for name, url in gtk_repos:
            dest = os.path.join(themes_dir, name)
            if not os.path.isdir(dest):
                subprocess.run(["git", "clone", "--depth=1", url, dest], check=True)

        for name, url in icon_repos:
            dest = os.path.join(icons_dir, name)
            if not os.path.isdir(dest):
                subprocess.run(["git", "clone", "--depth=1", url, dest], check=True)

        # Finally, bind‐mount these into the container
        svc = self.compose_data['services']['fb_service']
        vols = svc.setdefault("volumes", [])
        vols.extend([
            f"{themes_dir}:/usr/share/themes:ro",
            f"{icons_dir}:/usr/share/icons:ro"
        ])

    def _connect_vnc(self):
        self.vnc_client = api.connect(f"{self.ip_address}::5900", password="12345", timeout=1)
        while not self._known_mouse:
            try:
                self.vnc_client.mouseMove(2, self.TOOLBAR_MARGIN+2)
                self._known_mouse = (2, self.TOOLBAR_MARGIN+2)
            except:
                self.vnc_client = api.connect(f"{self.ip_address}::5900", password="12345", timeout=1)
                pass
                    
    def _set_screen(self, v):
        self._latest_screen = v

    def getBlankScreen(self, mode="rgb_array"):
        return np.zeros((self.height, self.width, 3), dtype=np.int8)
    
    def getScreen(self, mode="rgb_array", timeout=None, poll_interval=0.25):
        """
        Capture and return a screenshot from the VNC connection, but wait
        until the image is less than 90% black so we don’t return a
        still-loading (mostly-black) screen.

        :param mode: "pil" for a PIL.Image, "rgb_array" for a numpy array
        :param timeout: max seconds to wait before giving up (None = infinite)
        :param poll_interval: seconds between retries
        """
        import time

        if not self.vnc_client:
            self._connect_vnc()

        start = time.time()
        while True:
            try:
                # grab one frame into self._latest_screen
                self.vnc_client.captureRegionPIL(
                    self._set_screen,
                    0, self.TOOLBAR_MARGIN,
                    self.width, self.height
                )
                img = self._latest_screen.convert('RGB')
                arr = np.array(img, dtype=np.uint8)

                # convert to grayscale luminance
                # weights: 0.2989 R, 0.5870 G, 0.1140 B
                lum = (0.2989 * arr[...,0] +
                       0.5870 * arr[...,1] +
                       0.1140 * arr[...,2])

                # fraction of pixels below "black" threshold
                black_pixels = np.count_nonzero(lum < 16)
                frac_black = black_pixels / lum.size

                # if not >90% black, we’re ready
                if frac_black <= 0.9:
                    break

                # optional timeout
                if timeout is not None and (time.time() - start) > timeout:
                    break

                time.sleep(poll_interval)

            except Exception:
                # on any VNC hiccup, re-connect and retry
                self.vnc_client = None
                self._connect_vnc()

        # return in requested format
        if mode == "pil":
            return img
        elif mode == "rgb_array":
            return arr
        else:
            return None
    
    def nudgeMouse(self, dx, dy):
        if not self.vnc_client:
            self._connect_vnc()
        try:
            x, y = self._known_mouse
            newmouse = (int(min(max(0, x+dx), self.width-1)), int(min(max(0, y-self.TOOLBAR_MARGIN+dy), self.height-1)+self.TOOLBAR_MARGIN))
            self.vnc_client.mouseMove(*newmouse)
            self._known_mouse = newmouse
            return True
        except Exception as e:
            self.vnc_client = None
            return False

    def setMouse(self, x, y):
        """Set the mouse position on the VNC connection."""
        if not self.vnc_client:
            self._connect_vnc()
        try:
            newmouse = (int(min(max(0, x), self.width-1)), int(min(max(0, y), self.height-1)+self.TOOLBAR_MARGIN))
            self.vnc_client.mouseMove(*newmouse)
            self._known_mouse = newmouse
            return True
        except Exception as e:
            self.vnc_client = None
            return False

    def click(self, button=1):
        """Click the mouse button on the VNC connection."""
        if not self.vnc_client:
            self._connect_vnc()
        try:
            self.vnc_client.mousePress(button)
            return True
        except Exception as e:
            self.vnc_client = None
            return False
    
    def mouseHoldStart(self, button=1):
        """Press the mouse button on the VNC connection."""
        if not self.vnc_client:
            self._connect_vnc()
        try:
            self.vnc_client.mouseDown(button)
            self.isMouseDown = True
            return True
        except Exception as e:
            self.vnc_client = None
            return False

    def mouseHoldEnd(self, button=1):
        """Release the mouse button on the VNC connection."""
        if not self.vnc_client:
            self._connect_vnc()
        try:
            self.vnc_client.mouseUp(button)
            self.isMouseDown = False
            return True
        except Exception as e:
            self.vnc_client = None
            return False
        
    def keyDown(self, key):
        """Release the mouse button on the VNC connection."""
        if not self.vnc_client:
            self._connect_vnc()
        try:
            self.vnc_client.keyDown(key)
            return True
        except Exception as e:
            self.vnc_client = None
            return False
        
    def keyUp(self, key):
        """Release the mouse button on the VNC connection."""
        if not self.vnc_client:
            self._connect_vnc()
        try:
            self.vnc_client.keyUp(key)
            return True
        except Exception as e:
            self.vnc_client = None
            return False
        
    def keyPress(self, key):
        """Release the mouse button on the VNC connection."""
        if not self.vnc_client:
            self._connect_vnc()
        try:
            self.vnc_client.keyPress(key)
            return True
        except Exception as e:
            self.vnc_client = None
            return False
        
        
    def close(self):
        """Stop and remove the container, return the IP address to the pool, delete the temp directory, and close VNC."""
        try:
            subprocess.run(
                ["docker-compose", "-f", self.modified_compose_file.name, "down"],
                check=True,
                env=dict(os.environ, COMPOSE_PROJECT_NAME=self.project_name)
            )
        except subprocess.CalledProcessError as e:
            print(f"Error stopping container: {e}")

        # Close the VNC connection if it's open
        if self.vnc_client:
            self.vnc_client.disconnect()

        self._stop_pipe.set()

        try:
            os.remove(self.pipe_path)
        except:
            pass

        # Release the IP back to the pool and clean up resources
        with FBEnvironment._lock:
            FBEnvironment._available_ips.append(self.ip_address)
            
        # Remove the instance from the class-level dictionary
        FBEnvironment._instances.pop(self.ip_address, None)

        # Remove the modified compose file if it exists
        try:
            if os.path.exists(self.modified_compose_file.name):
                os.remove(self.modified_compose_file.name)
        except PermissionError as e:
            print(f"Permission error when trying to delete file {self.modified_compose_file.name}: {e}")



    def __del__(self):
        """Ensure the container is closed, IP returned, and VNC disconnected on object deletion."""
        self.close()


    def _populate_random_files(self, root, templates):
        # parse_size as before…
        def _parse_size(size_str):
            m = re.match(r'^\s*([\d.]+)\s*(B|KB|MB|GB)\s*$', size_str, re.IGNORECASE)
            if not m:
                raise ValueError(f"Cannot parse size: {size_str!r}")
            num, unit = m.groups()
            num = float(num)
            unit = unit.upper()
            mult = {'B':1, 'KB':1024, 'MB':1024**2, 'GB':1024**3}[unit]
            return int(num * mult)

        if templates is None:
            os.makedirs(root, exist_ok=True)
            open(os.path.join(root, "example.txt"), "wb").close()
            return

        dirs = []  # collect all created directories
        now = time.time()

        # 1) Create everything
        chosen = random.choice([
            fn for fn in os.listdir(templates)
            if os.path.isfile(os.path.join(templates, fn))
        ])
        with open(os.path.join(templates, chosen), encoding='utf-8') as f:
            lines = [L.rstrip() for L in f if L.strip()]

        self._initial_template_lines = lines

        print("Chosen: ", os.path.join(templates, chosen))

        indent = 2
        stack = []

        for line in lines:
            leading = len(line) - len(line.lstrip(' '))
            level = leading // indent
            entry = line.lstrip(' ')

            if entry.endswith('/'):
                # directory
                stack = stack[:level] + [entry[:-1]]
                path = os.path.join(root, *stack)
                os.makedirs(path, exist_ok=True)
                dirs.append(path)
            else:
                # file + size
                # file + size; but name may include subpaths
                name_part, size_part = entry.rsplit('(', 1)
                rel_name = name_part.strip()
                size     = _parse_size(size_part.rstrip(')'))

                # first build the full path under root + any stack prefix
                full_path = os.path.join(root, *stack[:level], rel_name)

                # **ensure all parent dirs exist, including any in rel_name**
                parent_dir = os.path.dirname(full_path)
                os.makedirs(parent_dir, exist_ok=True)

                # now create/truncate the file
                with open(full_path, 'wb') as f:
                    f.truncate(size)

                # file mtime
                f_mtime = now - random.uniform(0, 365*24*3600)
                os.utime(full_path, (f_mtime, f_mtime))


        # 2) Stamp directory mtimes *after* all children exist
        for d in dirs:
            d_mtime = now - random.uniform(0, 30*24*3600)
            os.utime(d, (d_mtime, d_mtime))

    def get_directory_tree(self) -> str:
        """
        Return a textual representation of the current directory tree under self.homedir,
        using two-space indentation per level and directories ending with '/',
        but *skipping* our Nautilus runtime files so they never show up.
        """
        import os

        # only these exact names are hidden; any other dot-entry (from your templates) still appears
        ignore = {'.dbus', '.hidden'}
        lines = []

        def walk(path: str, level: int):
            indent = " " * (2 * level)
            try:
                entries = sorted(os.listdir(path))
            except PermissionError:
                return
            for name in entries:
                if name in ignore:
                    continue
                full = os.path.join(path, name)
                if os.path.isdir(full):
                    lines.append(f"{indent}{name}/")
                    walk(full, level + 1)
                else:
                    lines.append(f"{indent}{name}")

        walk(self.homedir, 0)
        return "\n".join(lines)
    
    def get_template_tree(self) -> str:
        """
        Return the original tree structure from the chosen template,
        stripped of all size annotations, using the same two-space
        indentation and trailing '/' for directories.
        """
        # Requires that `_populate_random_files` saved the raw template lines:
        #     self._initial_template_lines = [L.rstrip('\n') for L in f if L.strip()]
        raw = getattr(self, "_initial_template_lines", [])
        out = []
        for line in raw:
            # preserve indentation
            indent = len(line) - len(line.lstrip(' '))
            entry = line.strip()
            # remove size annotation, if present
            if '(' in entry:
                entry = entry[:entry.rfind('(')].rstrip()
            out.append(" " * indent + entry)
        return "\n".join(out)


    def _generate_instruction(self):
        """Pick a random file and either 'move' it or 'delete' it."""
        # scan what's on disk
        all_paths = []
        for dp, dn, filenames in os.walk(self.homedir):
            for fn in filenames:
                all_paths.append((dp, fn))

        src_dir, fn = random.choice(all_paths)
        rel_src = os.path.relpath(src_dir, self.homedir)
        action = random.choice(["move", "delete"])

        if action == "move":
            # pick or create a target dir
            possible_dirs = [d for d in os.listdir(self.homedir)
                             if os.path.isdir(os.path.join(self.homedir, d))]
            dest_dir = random.choice(possible_dirs)
            instruction = f"move {fn} into the directory '{dest_dir}'"
            condition = lambda: (
                os.path.exists(os.path.join(self.homedir, dest_dir, fn))
                and not os.path.exists(os.path.join(src_dir, fn))
            )
        else:
            instruction = f"delete the document {fn}"
            condition = lambda: not os.path.exists(os.path.join(src_dir, fn))

        self._instruction = instruction
        self._condition = condition
        #print("TASK:", instruction)

    def wait_for_task(self, poll_interval=1.0, timeout=None):
        """
        Block until the human has carried out the TASK over VNC.
        Prints a confirmation when done.
        """
        start = time.time()
        while True:
            if self._condition():
                print("✅ Task completed:", self._instruction)
                return True
            if timeout and (time.time() - start) > timeout:
                print("❌ Timeout waiting for task.")
                return False
            time.sleep(poll_interval)


    def getCurrentPath(self):
        """
        Uses xdotool inside the container to fetch the Nautilus window title,
        then parses out the path after the “— ”.
        """
        # docker-compose names: {project_name}_fb_service_1
        container_name = f"{self.project_name}_fb_service_1"
        try:
            # Run xdotool in the container
            result = FBEnvironment._docker_client.containers \
                .get(container_name) \
                .exec_run(
                    ["xdotool", "getactivewindow", "getwindowname"],
                    stdout=True, stderr=True
                )
            title = result.output.decode("utf-8").strip()
            # Expect something like "Files — /config/photos"
            if "—" in title:
                # split on em-dash (you may need to adjust if it’s a hyphen)
                path = title.split("—", 1)[1].strip()
            elif "-" in title:
                # fallback on hyphen
                path = title.split("-", 1)[1].strip()
            else:
                # no delimiter found
                path = title
            return path
        except Exception as e:
            print(f"[getCurrentPath] error: {e}")
            return None




class FBGymEnv(gym.Env):
    """
    Custom Environment for Particle Simulation compatible with Gymnasium.
    """
    metadata = {'render_modes': ['rgb_array']}
    _all_time_seen = {}
    
    def __init__(self, maxsteps=30, actionmode='relative',  width=500, height=500, statemode='full', statewidth=100, stateheight=100, subnet=20, runtime_args=None, cautious_mode=False, reward_function=None, done_function=None):
        super(FBGymEnv, self).__init__()
        
        self.cautious_mode = cautious_mode

        if reward_function is None:
            self.reward_function = lambda oldpath, newpath, oldstate, newstate, oldview, newview: 0 if oldview == newview else 1
        else:
            self.reward_function = reward_function

        self.fresh = True
        
        if done_function is None:
            self.done_function = lambda oldpath, newpath, oldstate, newstate, oldview, newview: oldview != newview
        else:
            self.done_function = done_function

        if not runtime_args:
            runtime_args = {}

        # Initialize the ParticleSimulation with given parameters
        self.browser = FBEnvironment(height=height, width=width, subnet=subnet, **runtime_args)
        
        self.maxsteps = maxsteps

        self.statewidth = statewidth
        self.stateheight = stateheight

        self.actionmode = actionmode
        self.statemode = statemode

        self.stepcount = 0

        # Define the action space: (hit, x, y)
        if self.actionmode == "relative":
            self.action_space = spaces.Discrete(9)
        elif self.actionmode == "absolute":
            self.action_space = spaces.Tuple((
                spaces.Discrete(width), 
                spaces.Discrete(height)
            ))
        else:
            raise Exception("Unknown action type, use 'relative' or 'absolute'")

        if self.statemode == "full":
            self.observation_space = spaces.Box(low=0, high=255, shape=(width, height, 3), dtype=np.uint8)
        elif self.statemode == "zoomed":
            self.observation_space = spaces.Box(low=0, high=255, shape=(self.statewidth, self.stateheight, 3), dtype=np.uint8)
        elif self.statemode == "both":
            print("WARNING: Using 'both' mode means that observation_space will not be set")
        else:
            raise Exception("Unknown state type, use 'full' or 'zoomed'")

        
        # Rendering options
        self.render_mode = None
        self.width = width
        self.height = height

        self.last_path = self.browser._lastKnownPath
        self.last_state = self.browser.get_directory_tree()
        self.last_view = self.browser._lastKnownViewMode


    def convert_to_state(self, data, x, y):
        height, width, channels = data.shape

        # Define cropping bounds
        left = x - self.statewidth // 2
        right = x + self.statewidth // 2
        top = y - self.stateheight // 2
        bottom = y + self.stateheight // 2

        # Create a blank image for the output
        cropped_image = np.zeros((self.stateheight, self.statewidth, channels), dtype=data.dtype)

        # Calculate the region to copy from the original image
        src_x1 = max(0, left)
        src_x2 = min(width, right)
        src_y1 = max(0, top)
        src_y2 = min(height, bottom)

        # Calculate the corresponding region in the output image
        dst_x1 = max(0, -left)
        dst_x2 = self.statewidth - max(0, right - width)
        dst_y1 = max(0, -top)
        dst_y2 = self.stateheight - max(0, bottom - height)

        # Copy the valid region from the original image to the output image
        cropped_image[dst_y1:dst_y2, dst_x1:dst_x2] = data[src_y1:src_y2, src_x1:src_x2]

        return cropped_image
    
    def _getState(self):

        if self.statemode == "zoomed":
            state = self.convert_to_state(self.browser.getScreen(), self.browser._known_mouse[0], self.browser._known_mouse[1]-self.browser.TOOLBAR_MARGIN)
        elif self.statemode == "full":
            state = self.browser.getScreen()
        elif self.statemode == "both":
            state = self.browser.getScreen(), self.convert_to_state(self.browser.getScreen(), self.browser._known_mouse[0], self.browser._known_mouse[1]-self.browser.TOOLBAR_MARGIN)

        return state

    def reset(self, seed=None, options=None):
        """
        Reset the simulation to start over.
        """
        # Seeding

        if not self.fresh:
            super().reset(seed=seed)
            self.stepcount = 0
            self.browser.reset()
            self.browser.setMouse(random.randrange(0, self.browser.height), random.randrange(0, self.browser.width))


            self.last_path = self.browser._lastKnownPath
            self.last_state = self.browser.get_directory_tree()
            self.last_view = self.browser._lastKnownViewMode
            
        self.fresh = False

        return self._getState(), {}

    def step(self, action):
        """
        Execute the given action in the simulation environment.
        """

        if self.stepcount > self.maxsteps:
            return self._getState(), 0, True, False, {"mouse_held": self.browser.isMouseDown}

        self.stepcount += 1

        if self.actionmode == "absolute":
            x, y = action
            self.browser.setMouse(x, y)
            self.browser.click()

        elif self.actionmode == "relative":
            delta = 40
            if action == 0:
                self.browser.nudgeMouse(delta, 0)
            elif action == 1:
                self.browser.nudgeMouse(delta/2, delta/2)
            elif action == 2:
                self.browser.nudgeMouse(0, delta)
            elif action == 3:
                self.browser.nudgeMouse(-delta/2, delta/2)
            elif action == 4:
                self.browser.nudgeMouse(-delta, 0)
            elif action == 5:
                self.browser.nudgeMouse(-delta/2, -delta/2)
            elif action == 6:
                self.browser.nudgeMouse(0, -delta)
            elif action == 7:
                self.browser.nudgeMouse(delta/2, -delta/2)
            elif action == 8:
                self.browser.click()
                # time.sleep(0.3)
            elif action == 9:
                if self.browser.isMouseDown:
                    self.browser.mouseHoldEnd()
                else:
                    self.browser.mouseHoldStart()
                    self.browser.awaitMouseDown()
            

        new_path = self.browser._lastKnownPath
        new_state = self.browser.get_directory_tree()
        new_view = self.browser._lastKnownViewMode

        reward = self.reward_function(self.last_path, new_path, self.last_state, new_state, self.last_view, new_view)


        if self.stepcount > self.maxsteps:
            done = True
        else:
            done = self.done_function(self.last_path, new_path, self.last_state, new_state, self.last_view, new_view)
            if done:
                self.stepcount = 10000


        self.last_path = new_path
        self.last_state = new_state
        self.last_view = new_view
        
        return self._getState(), reward, done, False, {"mouse_held": self.browser.isMouseDown}

            
    def render(self):
        return self.browser.getScreen()

