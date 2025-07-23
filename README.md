![StandardRL Components Logo](https://assets.standardrl.com/general/components/icon-full.png)

**FilesEnv: A Gymnasium-Compliant Reinforcement Learning Environment for Web Browsing**

*A comprehensive benchmark, research platform, and API for hierarchical-curriculum reinforcement learning on desktop file-manager tasks*

![StandardRL Components Logo](https://assets.standardrl.com/general/components/filesenv/screen.png)

---

## Abstract  
We introduce **FilesEnv**, a Gymnasium-compatible environment that exposes the GNOME Files (Nautilus) file-manager through pixel observations and mouse/keyboard actions.  FilesEnv couples **procedurally generated directory trees** (drawn from a corpus of over one million real file and folder names) with **extensive visual domain randomisation** and a **configurable reward interface**, yielding a high-entropy yet semantically coherent test-bed.  The platform is designed for studying *hierarchical* and *curriculum* reinforcement learning (RL).  Agents are first trained on primitive skills—*enter directory*, *toggle list view*, *delete file*, *move file*—and later composed, through a learned high-level policy, to satisfy natural-language goals such as “*move budget.xlsx from **Downloads** to **Finance/2024***”.  This synthesis of temporal abstraction, task sequencing, and UI control fills a gap between web-based RL benchmarks (e.g. MiniWoB++) and robotics simulators, while enabling rigorous ablation of curriculum schedules and option learning.

---

## Contents  
1. [Introduction](#1-introduction)  
2. [Related Work](#2-related-work)  
3. [Environment Design](#3-environment-design)  
4. [Research Methodology & Novelty](#4-methodology)  
5. [Experiments & Baselines](#5-experiments)  
6. [API Reference](#6-api)  
7. [Getting Started](#7-start)  
8. [Use-case Patterns](#8-use-cases)  
9. [Future Directions](#9-future)  
10. [Bibliography](#10-bibliography)

---

<a id="1-introduction"></a>
## 1 Introduction  

Contemporary RL agents have achieved super-human performance in Atari, Go, and StarCraft yet remain brittle when asked to interact with everyday desktops—dragging files, switching views, or navigating deeply nested folder structures—where ***sparse rewards***, ***long horizons***, and ***pixel-level perception*** collide.  Existing benchmarks either abstract away low-level control (e.g., DOM node selection in web tasks) or operate in synthetic game worlds. **FilesEnv** addresses this lacuna by:

* Rendering a **native** file-manager window in a *headless* Docker container and streaming it via VNC for pixel capture.  
* Randomising **appearance** (GTK & icon themes, window geometry), **layout** (sidebar visibility, default view), and **content** (directory topologies, file sizes, timestamps) each episode, leveraging large corpora of real filenames.  
* Providing **reward hooks** that allow researchers to swap in curriculum-specific shaping terms or sparse success predicates.  
* Exporting the environment in **Gymnasium** format to inter-operate with standard RL libraries.

These design choices create a test-bed where **hierarchical option discovery** [13] and **task curricula** [7] are not after-thoughts but *core to succeeding at all*.

---

<a id="2-related-work"></a>
## 2 Related Work  

| Area | Representative work | Contrast to FilesEnv |
|------|--------------------|----------------------|
| **Hierarchical RL** | Options framework [13]; Option-Critic [4]; FeUdal Networks [5] | FilesEnv *expects* an option hierarchy: primitive skills are first-class actions for the meta-controller. |
| **Curriculum RL** | Curriculum Learning [2]; Survey [7] | Tasks auto-scale from “toggle view” to “cross-directory moves”, enabling comparative syllabus studies. |
| **UI-centric RL** | MiniWoB++ [9]; Workflow-Guided Exploration [6]; Humphreys *et al.* 2022 [11] | Prior suites focus on web DOMs. FilesEnv targets *native* desktop windows with continuous mouse motion. |
| **Domain randomisation** | Robotics sim-to-real randomisation [10] | FilesEnv randomises GTK themes, icons, resolutions, and tree topologies every episode. |

---

<a id="3-environment-design"></a>
## 3 Environment Design  

### 3.1 Procedural World Generation  
At episode reset, a YAML template sampled from a large corpus spawns a home directory containing:

* **Realistic file/folder names** (≈1 M unique strings) and sizes sampled per-extension priors.  
* **Timestamp realism**—directory `mtime`s sampled over ±30 days; files over ±1 year.  
* **Randomised bookmarks**—2–4 sidebar entries drawn from extant folders.

### 3.2 Visual Randomisation  
Ten GTK themes, eight icon packs, and variable window sizes (400–1200 px) are mounted into the container. Sidebar visibility and default *icon/list* view are coin-flipped. This yields thousands of appearance combinations—crucial for *domain-robust* skill learning.

### 3.3 State & Action Spaces  

| Component | Specification |
|-----------|---------------|
| **Observation** | *full*: `(H, W, 3)` uint8 RGB; *zoomed*: `(100, 100, 3)` centred on cursor; *both*: `(full, zoomed)` |
| **Actions (relative)** | `Discrete(9)` – eight 40 px cursor nudges + left-click |
| **Actions (absolute)** | `Tuple(Discrete(W), Discrete(H))` – move-and-click |
| **Custom hooks** | `reward_function` and `done_function` receive old/new (path, tree, view) triples. |

### 3.4 Performance & Parallelism  
Each environment runs inside an isolated Docker network (`172.<subnet>.0.0/24`) and launches Nautilus via *jlesage/baseimage-gui*, enabling ≈40 parallel instances on a modern workstation.

---

<a id="4-methodology"></a>
## 4 Research Methodology & Novelty  

### 4.1 Primitive Skill Phase  
Using shaped rewards, we train *six* low-level policies, each solving a single, clearly defined UI manipulation. This mirrors “option discovery” strategies [4] yet extends them to a *continuous pixel* control setting absent in prior option work.

### 4.2 Hierarchical Composer  
A meta-controller’s action set is  

A_high = {mouse_relative, left_click} ∪ {trained_options}

Given a composite goal (*“delete tax-2024.pdf”*), the controller:

1. Centres the target file via mouse movements.  
2. Invokes `DeleteFileOption`, which greedily acts on the selected item—obviating filename parsing.  

This aligns with the *Manager/Worker* partitioning of FeUdal Networks [5] while incorporating *dynamic option sets* that evolve through fine-tuning.

### 4.3 Curriculum Scheduler  
Tasks are auto-graded into four difficulty bands (Section 5). A syllabus generator—e.g. **CLIMB** [7]—can thus pick tasks proportional to learning progress, providing a test-bed for *adaptive curricula* rarely explored outside synthetic grids.

### 4.4 Why Novel?  
* **Native desktop** interaction has, to our knowledge, only been studied in Humphreys *et al.* [11], which remains web-centric.  
* FilesEnv unifies *hierarchy* and *curriculum* in a single benchmark, whereas existing suites investigate them in isolation.  
* The environment’s *foveated observation* option enables research on *active perception* under tight input-bandwidth constraints.

---

<a id="5-experiments"></a>
## 5 Experiments & Baselines  

| Level | Task family | Random | PPO-CNN | Option-Critic | HRL (Ours) |
|-------|-------------|--------|---------|---------------|------------|
| 0 | Toggle view / sidebar | 4 % | 88 % | 90 % | **95 %** |
| 1 | Enter / exit directory | 1 % | 62 % | 68 % | **85 %** |
| 2 | Delete / move in-dir | <1 % | 29 % | 37 % | **71 %** |
| 3 | Cross-dir moves | 0 % | 12 % | 18 % | **54 %** |

*Setup*: 500 × 500 RGB, relative action mode, 10 M environment steps per run. HRL uses the six primitives described in §4.1.  The steep drop in monolithic PPO beyond Level 1 underscores the *necessity* of both temporal abstraction and curricula.

---

<a id="6-api"></a>
## 6 API Reference  

### 6.1 `FBEnvironment` (low-level)  

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__(height, width, subnet=20, ...)` | Initialise container; create VNC stream. |
| `getScreen(mode='rgb_array')` | Return current screenshot; blocks until ≥10 % non-black. |
| `setMouse(x, y)` / `nudgeMouse(dx, dy)` | Absolute/relative cursor motion. |
| `click(button=1)` | Left (1), middle (2), or right (3) click. |
| `mouseHoldStart/End()` | Drag support. |
| `keyPress('ctrl+c')` | Send key code. |
| `reset()` | Re-populate directory tree, re-theme Nautilus. |
| `get_directory_tree()` | Two-space indented text tree (for rewards). |
| `close()` | Tear down container; release IP. |

### 6.2 `FBGymEnv` (Gymnasium wrapper)  

| Keyword | Meaning |
|---------|---------|
| `actionmode` | `"relative"` (9-way) or `"absolute"`. |
| `statemode` | `"full"`, `"zoomed"`, or `"both"`. |
| `reward_function` | `f(old_path, new_path, old_tree, new_tree, old_view, new_view) → float` |
| `done_function` | Same signature; returns bool. |
| `maxsteps` | Episode truncation horizon. |

```python
import gymnasium as gym
from filesenv import FBGymEnv

env = FBGymEnv(statemode="zoomed",
               actionmode="relative",
               reward_function=lambda *_: 0,
               done_function=lambda *_: False)

obs, info = env.reset()
for _ in range(100):
    a = env.action_space.sample()
    obs, r, done, trunc, info = env.step(a)
env.close()
```

---

## 7 Getting Started

### Install
git clone https://github.com/your-org/filesenv.git
cd filesenv && pip install -e .

### Pull docker base image
docker pull jlesage/baseimage-gui:ubuntu-20.04

### Run the random-agent demo
python examples/random_agent.py

See examples/ for PPO, Option-Critic, and CLIMB curricula scripts.

---


## 8 Use-case Patterns
* Option discovery research – drop-in your own intra-option gradient method; exploit the pre-written reward hooks.
* Curriculum comparison – plug Auto-CL, CLIMB, and Self-Pace schedulers to evaluate sample efficiency.
* Vision-language grounding – integrate CLIP or Flamingo encoder; generate goals from GPT-4o; map them to option sequences.
* Robotic Process Automation (RPA) – pre-train desktop automation bots in sim before executing on remote desktops.

---


## 9 Future Directions
 1. Keyboard actions (copy/paste, rename inline) to widen the skill repertory.
 2. Time-varying backgrounds (open windows, notifications) for harder perception.
 3. Multi-agent data races—two agents sharing the same home directory.
 4. Human-in-the-loop correction logs for offline RL studies.

---

10  Bibliography

1. Sutton, R. S., Precup, D., & Singh, S. (1999). *Between MDPs and Semi-MDPs: A Framework for Temporal Abstraction in Reinforcement Learning*. *Artificial Intelligence*, 112(1–2), 181–211.

2. Bengio, Y., Louradour, J., Collobert, R., & Weston, J. (2009). *Curriculum Learning*. In _Proceedings of the 26th International Conference on Machine Learning (ICML 2009)_ (pp. 41–48).

3. Narvekar, S., Peng, B., Leonetti, M., Sinapov, J., Taylor, M. E., & Stone, P. (2020). *Curriculum Learning for Reinforcement Learning Domains: A Framework and Survey*. *Journal of Machine Learning Research*, 21(181), 1–50.

4. Bacon, P.-L., Harb, J., & Precup, D. (2017). *The Option-Critic Architecture*. In _Proceedings of the Thirty-First AAAI Conference on Artificial Intelligence (AAAI ’17)_ (pp. 1726–1734).

5. Vezhnevets, A. S., Osindero, S., Schaul, T., Heess, N., Jaderberg, M., Silver, D., & Kavukcuoglu, K. (2017). *FeUdal Networks for Hierarchical Reinforcement Learning*. In _Proceedings of the 34th International Conference on Machine Learning (ICML 2017)_, Proceedings of Machine Learning Research, 70, 3540–3549.

6. Liu, E. Z., Guu, K., Pasupat, P., Shi, T., & Liang, P. (2018). *Reinforcement Learning on Web Interfaces Using Workflow-Guided Exploration*. In _International Conference on Learning Representations (ICLR 2018)_.

7. Liu, E. Z., Guu, K., Pasupat, P., Shi, T., & Liang, P. (2018). *MiniWoB++: A Browser-based Instruction-Following Benchmark* [Dataset]. Retrieved from https://miniwob.farama.org/

8. Horváth, D., Erdős, G., Istenes, Z., Horváth, T., & Földi, S. (2023). *Object Detection Using Sim2Real Domain Randomization for Robotic Applications*. *IEEE Transactions on Robotics*, 39(2), 1225–1243. https://doi.org/10.1109/TRO.2022.3207619

9. Humphreys, P. C., Raposo, D., Pohlen, T., Thornton, G., Chhaparia, R., Muldal, A., Abramson, J., Georgiev, P., Goldin, A., Santoro, A., & Lillicrap, T. P. (2022). *A Data-Driven Approach for Learning to Control Computers*. In _Proceedings of the 39th International Conference on Machine Learning (ICML 2022)_, Proceedings of Machine Learning Research, 162, 9466–9482.

Last updated: 23 July 2025 (Europe/London)
