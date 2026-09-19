# Dynamic Memory Index — keyword,keyword,keyword → file.md
# One line per topic file. This file IS the index: it is injected verbatim
# into the system prompt at session start. Topic files stay on disk and are
# read only when a line routes to them.
#
# Routing: score each line's whole keyword SET against the conversation, and
# prefer the line that fits best overall — not the first line sharing a word.
# Follow obviously related terms that are not spelled out in a line.
#
# Qualifier prefixes (user-assigned only):
#   !! critical — never edit without explicit user approval
#   !  pinned   — never prune
java,springframework,jvm,garbagecollection,heap,profiling,jmx → java-performance.md
javascript,typescript,npm,bundler,webpack,vite,node,lint → js-toolchain.md
database,postgres,index,query,explain,migration,vacuum → postgres-notes.md
python,venv,packaging,poetry,ruff,pytest,typing → python-env.md
deploy,release,pipeline,staging,rollback,canary,ci → deploy-pipeline.md
git,branch,rebase,worktree,conflict,cherrypick,stash → git-workflow.md
laptop,thinkpad,firmware,battery,thermal,fankey,bios → laptop-hardware.md
router,firmware,openwrt,modem,subnet,dns,dhcp → home-network.md
