# Homebrew formula for Codo. Kept up to date by .github/workflows/release.yml.
#   brew tap DomaAI/codo https://github.com/DomaAI/Codo && brew install codo
class Codo < Formula
  desc "Team of AI agents on the plans you already pay for: Claude Code, Codex, Gemini CLI, any API"
  homepage "https://domaai.pl/en/codo"
  version "0.32.5"
  license "Apache-2.0"

  on_macos do
    on_arm do
      url "https://github.com/DomaAI/Codo/releases/download/v0.32.5/codo-macos-arm64"
      sha256 "6d39337f233b2697f276f68f0e9fbafd953dd9ad2a2ee7724b6da82cc191834c"
    end
    on_intel do
      url "https://github.com/DomaAI/Codo/releases/download/v0.32.5/codo-macos-x64"
      sha256 "d6f972266d4f4383cc90a858e7dfb73c5cd4aec14f35a0137e73ab9375800779"
    end
  end

  on_linux do
    on_arm do
      url "https://github.com/DomaAI/Codo/releases/download/v0.32.5/codo-linux-arm64"
      sha256 "39a6c57ba031ffb3dba1851c7be608a83c77c5e9ae5864d9868da6be36557dc8"
    end
    on_intel do
      url "https://github.com/DomaAI/Codo/releases/download/v0.32.5/codo-linux-x64"
      sha256 "f43638f664eaa865b8a2a2630daa4042bdf351502808fac87d62b1bb9ba03d68"
    end
  end

  def install
    bin.install Dir["codo-*"].first => "codo"
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/codo --version")
  end
end
