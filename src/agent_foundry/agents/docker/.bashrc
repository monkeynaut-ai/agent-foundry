# Bash completion
if [ -f /etc/bash_completion ]; then
  . /etc/bash_completion
fi

# Git completion and prompt
if [ -f /usr/share/bash-completion/completions/git ]; then
  . /usr/share/bash-completion/completions/git
fi

# Git branch in prompt
__git_ps1() {
  local branch
  branch=$(git symbolic-ref --short HEAD 2>/dev/null || git rev-parse --short HEAD 2>/dev/null)
  [ -n "$branch" ] && printf " (%s)" "$branch"
}

# Prompt: user@container:dir (branch)$
PS1='\[\033[1;32m\]\u\[\033[0m\]@\[\033[1;34m\]container\[\033[0m\]:\[\033[1;33m\]\w\[\033[0;36m\]$(__git_ps1)\[\033[0m\]\$ '

# Aliases
alias ll='ls -alF'
alias la='ls -A'
alias l='ls -CF'
alias gs='git status'
alias gd='git diff'
alias gl='git log --oneline -20'
alias ..='cd ..'

# Python virtualenv — auto-activate if present in workspace
if [ -f /workspace/.venv/bin/activate ]; then
  . /workspace/.venv/bin/activate
fi
