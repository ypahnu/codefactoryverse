# CodeFactory Database Report - Updated
Generated: 2026-10-29T17:10:45.693773Z

Database: codefactoryverse/codefactory.db (SQLite)
Tables: agent, message_read, project, project_activity, project_sandbox, task, task_message, task_participants, team, team_members, user

## Summary Counts
| Table | Rows |
|-------|------|
| agent | 12 |
| message_read | 132 |
| project | 3 |
| project_activity | 0 |
| project_sandbox | 3 |
| task | 10 |
| task_message | 61 |
| task_participants | 0 |
| team | 3 |
| team_members | 4 |
| user | 2 |

## Table: `agent`
### Schema
| Column | Type | Nullable | PK | Default |
|--------|------|----------|----|---------|
| id | INTEGER | NO | YES |  |
| name | VARCHAR(120) | NO | NO |  |
| role | VARCHAR(100) | YES | NO |  |
| system_prompt | TEXT | NO | NO |  |
| skills_json | TEXT | NO | NO |  |
| task_id | INTEGER | NO | NO |  |
| status | VARCHAR(20) | YES | NO |  |
| model | VARCHAR(50) | YES | NO |  |
| created_at | DATETIME | YES | NO |  |
| cloned_from | VARCHAR(100) | YES | NO |  |
| last_active_at | DATETIME | YES | NO |  |
| lifespan_seconds | INTEGER | YES | NO | 3600 |
| expires_at | DATETIME | YES | NO |  |
| heartbeat_at | DATETIME | YES | NO |  |
| modal_sandbox_id | VARCHAR(100) | YES | NO |  |
| modal_status | VARCHAR(50) | YES | NO |  |

**Foreign Keys:**
- ['task_id'] -> task.['id']

### Data (first 10 rows)
- 1 Auth Specialist #1 role=Backend Security Eng task=1 alive=False expires_in=-171423s skills=12
- 2 a simple task to talk to bots Specialist #1 role=a simple task to tal task=4 alive=False expires_in=-170682s skills=1
- 3 jown role=a simple task to tal task=4 alive=False expires_in=-170517s skills=2
- 6 Jaysoon role=change the image siz task=6 alive=False expires_in=-161754s skills=12
- 7 robison role=change the image siz task=6 alive=False expires_in=-161630s skills=12
- 10 peter role=Task 1 Specialist task=5 alive=False expires_in=-161151s skills=12
- 11 JOANA_BOT role=Task 1 Specialist task=5 alive=False expires_in=-68889s skills=12
- 12 rod role=task2 Specialist task=7 alive=False expires_in=-155738s skills=12
- 13 rod2 role=task2 Specialist task=7 alive=False expires_in=-155631s skills=12
- 14 RIO role=task3 Specialist task=8 alive=False expires_in=-152877s skills=1

---

## Table: `message_read`
### Schema
| Column | Type | Nullable | PK | Default |
|--------|------|----------|----|---------|
| id | INTEGER | NO | YES |  |
| message_id | INTEGER | NO | NO |  |
| agent_id | INTEGER | NO | NO |  |
| read_at | DATETIME | YES | NO |  |

**Foreign Keys:**
- ['message_id'] -> task_message.['id']
- ['agent_id'] -> agent.['id']

**Unique Constraints:**
- uq_message_agent_read: ['message_id', 'agent_id']

### Data (first 10 rows)
- id=214 msg=61 agent=15 read_at=2026-10-29 17:10:28.012167
- id=213 msg=61 agent=11 read_at=2026-10-29 17:10:28.011721
- id=212 msg=61 agent=10 read_at=2026-10-29 17:10:28.010862
- id=211 msg=60 agent=15 read_at=2026-10-29 17:10:21.802382
- id=210 msg=60 agent=11 read_at=2026-10-29 17:10:21.801943
- id=209 msg=60 agent=10 read_at=2026-10-29 17:10:21.801156
- id=208 msg=58 agent=16 read_at=2026-10-28 03:02:44.210361
- id=207 msg=57 agent=16 read_at=2026-10-28 03:02:41.890650
- id=206 msg=56 agent=16 read_at=2026-10-28 03:02:02.888663
- id=205 msg=55 agent=16 read_at=2026-10-28 03:01:52.158945

---

## Table: `project`
### Schema
| Column | Type | Nullable | PK | Default |
|--------|------|----------|----|---------|
| id | INTEGER | NO | YES |  |
| name | VARCHAR(120) | NO | NO |  |
| slug | VARCHAR(120) | NO | NO |  |
| description | TEXT | YES | NO |  |
| team_id | INTEGER | NO | NO |  |
| owner_id | INTEGER | NO | NO |  |
| status | VARCHAR(20) | YES | NO |  |
| created_at | DATETIME | YES | NO |  |
| updated_at | DATETIME | YES | NO |  |
| color | VARCHAR(20) | YES | NO |  |

**Foreign Keys:**
- ['team_id'] -> team.['id']
- ['owner_id'] -> user.['id']

### Data (first 10 rows)
- 1 CodeFactory API slug=codefactory-api team=1 owner=1 tasks=8 sandbox=proj-core-factory-codefactory-api-1
- 2 project 1 slug=project-1 team=2 owner=2 tasks=1 sandbox=proj-team-1-project-1-2
- 3 Shoes Page slug=shoes-page team=3 owner=1 tasks=1 sandbox=proj-acme-corp-shoes-page-3

---

## Table: `project_activity`
### Schema
| Column | Type | Nullable | PK | Default |
|--------|------|----------|----|---------|
| id | INTEGER | NO | YES |  |
| project_id | INTEGER | NO | NO |  |
| task_id | INTEGER | YES | NO |  |
| agent_id | INTEGER | YES | NO |  |
| user_id | INTEGER | YES | NO |  |
| type | VARCHAR(50) | NO | NO |  |
| summary | VARCHAR(300) | NO | NO |  |
| detail | TEXT | YES | NO |  |
| created_at | DATETIME | YES | NO |  |

**Foreign Keys:**
- ['project_id'] -> project.['id']
- ['task_id'] -> task.['id']
- ['agent_id'] -> agent.['id']
- ['user_id'] -> user.['id']

### Data (first 10 rows)
- No activities yet

---

## Table: `project_sandbox`
### Schema
| Column | Type | Nullable | PK | Default |
|--------|------|----------|----|---------|
| id | INTEGER | NO | YES |  |
| project_id | INTEGER | NO | NO |  |
| name | VARCHAR(120) | NO | NO |  |
| display_name | VARCHAR(120) | YES | NO |  |
| type | VARCHAR(30) | YES | NO |  |
| runtime | VARCHAR(20) | YES | NO |  |
| status | VARCHAR(30) | YES | NO |  |
| modal_sandbox_id | VARCHAR(100) | YES | NO |  |
| modal_app_id | VARCHAR(100) | YES | NO |  |
| image | VARCHAR(120) | YES | NO |  |
| volume_name | VARCHAR(120) | YES | NO |  |
| cpu | FLOAT | YES | NO |  |
| memory | INTEGER | YES | NO |  |
| timeout | INTEGER | YES | NO |  |
| idle_timeout | INTEGER | YES | NO |  |
| returncode | INTEGER | YES | NO |  |
| tunnel_enabled | BOOLEAN | YES | NO |  |
| tunnel_port | INTEGER | YES | NO |  |
| tunnel_url | VARCHAR(512) | YES | NO |  |
| tunnel_urls_json | TEXT | YES | NO |  |
| tunnel_last_seen | DATETIME | YES | NO |  |
| git_repo_url | VARCHAR(512) | YES | NO |  |
| git_branch | VARCHAR(100) | YES | NO |  |
| dev_command | VARCHAR(256) | YES | NO |  |
| install_command | VARCHAR(512) | YES | NO |  |
| snapshot_image_id | VARCHAR(100) | YES | NO |  |
| snapshot_created_at | DATETIME | YES | NO |  |
| env_vars_json | TEXT | YES | NO |  |
| created_at | DATETIME | YES | NO |  |
| last_heartbeat | DATETIME | YES | NO |  |
| expires_at | DATETIME | YES | NO |  |
| last_started_at | DATETIME | YES | NO |  |
| last_stopped_at | DATETIME | YES | NO |  |

**Foreign Keys:**
- ['project_id'] -> project.['id']

### Data (first 10 rows)
- 1 proj-core-factory-codefactory-api-1 project=1 status=unknown volume=codefactory-vol-core-factory-codefactory-api tunnel=none alive=False
- 2 proj-team-1-project-1-2 project=2 status=unknown volume=codefactory-vol-team-1-project-1 tunnel=none alive=False
- 3 proj-acme-corp-shoes-page-3 project=3 status=unknown volume=codefactory-vol-acme-corp-shoes-page tunnel=none alive=False

---

## Table: `task`
### Schema
| Column | Type | Nullable | PK | Default |
|--------|------|----------|----|---------|
| id | INTEGER | NO | YES |  |
| title | VARCHAR(200) | NO | NO |  |
| description | TEXT | YES | NO |  |
| full_prompt | TEXT | YES | NO |  |
| status | VARCHAR(20) | YES | NO |  |
| priority | VARCHAR(20) | YES | NO |  |
| project_id | INTEGER | NO | NO |  |
| creator_id | INTEGER | NO | NO |  |
| assignee_id | INTEGER | YES | NO |  |
| position | INTEGER | YES | NO |  |
| created_at | DATETIME | YES | NO |  |
| updated_at | DATETIME | YES | NO |  |
| due_date | DATETIME | YES | NO |  |

**Foreign Keys:**
- ['project_id'] -> project.['id']
- ['creator_id'] -> user.['id']
- ['assignee_id'] -> user.['id']

### Data (first 10 rows)
- 1 Implement User Auth System project=1 status=done agents=1 msgs=3 participants=0
- 2 Build Task Chat Timeline UI project=1 status=todo agents=0 msgs=0 participants=0
- 3 Agent Cloning Engine project=1 status=todo agents=0 msgs=0 participants=0
- 4 a simple task to talk to bots project=2 status=todo agents=2 msgs=0 participants=0
- 5 Task 1 project=1 status=done agents=3 msgs=25 participants=0
- 6 change the image size of the h project=1 status=todo agents=2 msgs=9 participants=0
- 7 task2 project=1 status=todo agents=2 msgs=13 participants=0
- 8 task3 project=1 status=in_progress agents=1 msgs=5 participants=0
- 9 task4 project=1 status=todo agents=1 msgs=5 participants=0
- 10 simple webpage project=3 status=todo agents=0 msgs=1 participants=0

---

## Table: `task_message`
### Schema
| Column | Type | Nullable | PK | Default |
|--------|------|----------|----|---------|
| id | INTEGER | NO | YES |  |
| task_id | INTEGER | NO | NO |  |
| agent_id | INTEGER | YES | NO |  |
| user_id | INTEGER | YES | NO |  |
| role | VARCHAR(20) | NO | NO |  |
| content | TEXT | NO | NO |  |
| full_prompt | TEXT | YES | NO |  |
| message_type | VARCHAR(30) | YES | NO |  |
| created_at | DATETIME | YES | NO |  |

**Foreign Keys:**
- ['task_id'] -> task.['id']
- ['agent_id'] -> agent.['id']
- ['user_id'] -> user.['id']

### Data (first 10 rows)
- 61 task=5 agent= role=user type=chat content=Hey @ypahnu can you join this task please?... reads=3
- 60 task=5 agent= role=user type=chat content=Hey @ypahnu can you join this task?... reads=3
- 59 task=10 agent= role=briefing type=briefing content=we need a web page with cards and showing the shoe... reads=0
- 58 task=9 agent=16 role=assistant type=log content=💡 Thought: For task4, I chose PostgreSQL + SQLAlch... reads=1
- 57 task=9 agent= role=user type=chat content=productpage_bot.. what's the price of jeans?... reads=1
- 56 task=9 agent=16 role=assistant type=chat content=Briefing: Creating product page for 3 products (je... reads=1
- 55 task=9 agent=16 role=system type=log content=Agent cloned: ProductPage_bot (task4 Specialist) •... reads=1
- 54 task=9 agent= role=briefing type=briefing content=Create a product page... reads=1
- 53 task=5 agent=15 role=assistant type=log content=🤖 Hugo (a beta tester) started on **Task 1** — Foc... reads=3
- 52 task=5 agent=10 role=assistant type=chat content=Task 1 briefing: Integrated "make it blue" broadca... reads=3

---

## Table: `task_participants`
### Schema
| Column | Type | Nullable | PK | Default |
|--------|------|----------|----|---------|
| task_id | INTEGER | NO | YES |  |
| user_id | INTEGER | NO | YES |  |
| added_via | VARCHAR(50) | YES | NO |  |
| added_at | DATETIME | YES | NO |  |
| added_by | INTEGER | YES | NO |  |

**Foreign Keys:**
- ['task_id'] -> task.['id']
- ['user_id'] -> user.['id']
- ['added_by'] -> user.['id']

### Data (first 10 rows)

---

## Table: `team`
### Schema
| Column | Type | Nullable | PK | Default |
|--------|------|----------|----|---------|
| id | INTEGER | NO | YES |  |
| name | VARCHAR(100) | NO | NO |  |
| slug | VARCHAR(100) | NO | NO |  |
| description | TEXT | YES | NO |  |
| owner_id | INTEGER | NO | NO |  |
| created_at | DATETIME | YES | NO |  |
| avatar_color | VARCHAR(20) | YES | NO |  |

**Foreign Keys:**
- ['owner_id'] -> user.['id']

**Unique Constraints:**
- None: ['slug']

### Data (first 10 rows)
- 1 Core Factory slug=core-factory owner=1 members=2 projects=1
- 2 team 1 slug=team-1 owner=2 members=1 projects=1
- 3 Acme Corp slug=acme-corp owner=1 members=1 projects=1

---

## Table: `team_members`
### Schema
| Column | Type | Nullable | PK | Default |
|--------|------|----------|----|---------|
| team_id | INTEGER | NO | YES |  |
| user_id | INTEGER | NO | YES |  |
| role | VARCHAR(20) | YES | NO |  |
| joined_at | DATETIME | YES | NO |  |

**Foreign Keys:**
- ['team_id'] -> team.['id']
- ['user_id'] -> user.['id']

### Data (first 10 rows)
- (1, 1, 'member', '2026-10-27 16:33:42.716173')
- (2, 2, 'member', '2026-10-27 16:36:20.817872')
- (3, 1, 'member', '2026-10-29 11:09:30.793596')
- (1, 2, 'member', '2026-10-29 17:10:25.216879')

---

## Table: `user`
### Schema
| Column | Type | Nullable | PK | Default |
|--------|------|----------|----|---------|
| id | INTEGER | NO | YES |  |
| username | VARCHAR(80) | NO | NO |  |
| email | VARCHAR(120) | NO | NO |  |
| password_hash | VARCHAR(256) | NO | NO |  |
| display_name | VARCHAR(120) | YES | NO |  |
| avatar_url | VARCHAR(256) | YES | NO |  |
| bio | TEXT | YES | NO |  |
| created_at | DATETIME | YES | NO |  |
| is_active | BOOLEAN | YES | NO |  |

### Data (first 10 rows)
| id | username | email | display_name |
|----|----------|-------|--------------|
| 1 | demo | demo@factory.local | Demo User |
| 2 | ypahnu | zveb@hotmail.com | andre webb |

---
