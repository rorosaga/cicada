# Cicada's Homebrew formula (G181). This repository is its own tap:
#
#   brew tap rorosaga/cicada https://github.com/rorosaga/cicada
#   brew install rorosaga/cicada/cicada        # the latest release; --HEAD follows dev
#   cicada-setup                               # memory folder, search model, agent hooks, background service
#
# It installs the backend, the MCP server and the `cicada` command with their Python environment. The background
# service is install.sh's (scripts/install-backend-agent.sh on a Mac, scripts/install-backend-service.sh on Linux),
# run by `cicada-setup`; there is deliberately no `service do` block (see scripts/cicada-setup.sh). The app is not a
# cask: a release app carries its own backend (scripts/install-release.sh installs it).
#
# The tag below is VERSION's: scripts/release/release.sh bump stamps it and check_version.py holds it equal.
class Cicada < Formula
  desc "Memory for your AI agents: a git-versioned markdown knowledge graph"
  homepage "https://github.com/rorosaga/cicada"
  url "https://github.com/rorosaga/cicada.git", tag: "v0.5.0"
  license "MIT"
  head "https://github.com/rorosaga/cicada.git", branch: "dev"

  depends_on "python@3.12"
  depends_on "uv"

  def install
    # Tracked runtime files only: no app sources, docs or tests.
    libexec.install %w[api mcp scripts skills SKILL.md VERSION LICENSE README.md install.sh]
    rm_r libexec/"api/tests"

    # One Python environment, from the developer lock without the optional larger model's runtime
    # (scripts/sync-server-env.sh), on Homebrew's own Python so nothing points into a temporary HOME.
    ENV["UV_PYTHON"] = formula_opt_bin("python@3.12")/"python3.12"
    ENV["UV_PYTHON_DOWNLOADS"] = "never"
    ENV["UV_CACHE_DIR"] = buildpath/".uv-cache"
    ENV["UV_LINK_MODE"] = "copy"
    system "bash", libexec/"scripts/sync-server-env.sh", "--quiet"

    bin.install_symlink libexec/"scripts/cicada"
    (bin/"cicada-setup").write <<~SH
      #!/bin/bash
      export CICADA_REPO="#{opt_libexec}"
      export CICADA_LOG_DIR="${CICADA_LOG_DIR:-#{var}/log/cicada}"
      exec /bin/bash "#{opt_libexec}/scripts/cicada-setup.sh" "$@"
    SH
  end

  # The settings file install.sh writes (api/.env) lives in etc, so an upgrade keeps it; logs live in var.
  post_install_steps do
    mkdir_p "log/cicada", base: :var
    mkdir_p "cicada", base: :etc
    unless_path_exists "cicada/api.env", base: :etc do
      touch "cicada/api.env", base: :etc
      set_permissions "cicada/api.env", "0600", base: :etc, recursive: false
    end
    symlink "cicada/api.env", "api/.env", source_base: :etc, target_base: :libexec, overwrite: true
  end

  def caveats
    <<~EOS
      Finish with:
        cicada-setup
      It creates the memory folder (~/cicada/memory), fetches the search model, connects
      Claude Code (and Codex) and starts the background service on 127.0.0.1:8000. Run it
      again after `brew upgrade cicada`; `cicada-setup --uninstall` undoes it (the memory stays).

      The backend writes its own API token to ~/.cicada/api_token. Settings: #{etc}/cicada/api.env.
      Logs: #{var}/log/cicada. The Mac app is a separate download: scripts/install-release.sh.
    EOS
  end

  test do
    assert_match "usage", shell_output("#{bin}/cicada --help").downcase
    system libexec/"api/.venv/bin/python", "-c", "import fastapi, uvicorn, onnxruntime, sqlite_vec"
    refute_path_exists libexec/"api/.venv/lib/python3.12/site-packages/torch"
    ENV["CICADA_MEMORY_PATH"] = testpath/"memory"
    ENV["CICADA_HOME"] = testpath/".cicada"
    ENV["PYTHONPATH"] = libexec
    system libexec/"api/.venv/bin/python", "-c", "import api.main"
  end
end
