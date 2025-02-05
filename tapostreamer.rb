class TapoStreamer < Formula
  include Language::Python::Virtualenv

  desc "TapoStreamer is an Python application that shows the video streaming from the cameras made by TP-Link."
  homepage "https://github.com/rioriost/Tapo_Streamer/"
  url "https://files.pythonhosted.org/packages/44/0a/85ebc29fa76b458a967fc9f479e8a3669994df1b179ae689e74804a8bf9e/tapostreamer-0.1.0.tar.gz"
  sha256 "b49788b114c0ea0638ccc2ed0da89f85903c48b5ed0fba0b0edebfcbcd662914"
  license "MIT"

  depends_on "python@3.11"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "tapostreamer", shell_output("#{bin}/tapostreamer --version")
  end
end
