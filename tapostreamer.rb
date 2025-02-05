class Tapostreamer < Formula
  include Language::Python::Virtualenv

  desc "TapoStreamer is an Python application that shows the video streaming from the cameras made by TP-Link."
  homepage "https://github.com/rioriost/Tapo_Streamer/"
  url "https://files.pythonhosted.org/packages/44/0a/85ebc29fa76b458a967fc9f479e8a3669994df1b179ae689e74804a8bf9e/tapostreamer-0.1.0.tar.gz"
  sha256 "b49788b114c0ea0638ccc2ed0da89f85903c48b5ed0fba0b0edebfcbcd662914"
  license "MIT"

  depends_on "python@3.11"

  resource "opencv-python" do
    url "https://files.pythonhosted.org/packages/05/4d/53b30a2a3ac1f75f65a59eb29cf2ee7207ce64867db47036ad61743d5a23/opencv_python-4.11.0.86-cp37-abi3-macosx_13_0_arm64.whl"
    sha256 "432f67c223f1dc2824f5e73cdfcd9db0efc8710647d4e813012195dc9122a52a"
    using :python_wheel
  end

  resource "numpy" do
    url "https://files.pythonhosted.org/packages/9c/e6/efb8cd6122bf25e86e3dd89d9dbfec9e6861c50e8810eed77d4be59b51c6/numpy-2.2.2-cp311-cp311-macosx_14_0_arm64.whl"
    sha256 "c7d1fd447e33ee20c1f33f2c8e6634211124a9aabde3c617687d8b739aa69eac"
    using :python_wheel
  end

  resource "keyring" do
    url "https://files.pythonhosted.org/packages/d3/32/da7f44bcb1105d3e88a0b74ebdca50c59121d2ddf71c9e34ba47df7f3a56/keyring-25.6.0-py3-none-any.whl"
    sha256 "552a3f7af126ece7ed5c89753650eec89c7eaae8617d0aa4d9ad2b75111266bd"
    using :python_wheel
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/tapostreamer"
  end
end
