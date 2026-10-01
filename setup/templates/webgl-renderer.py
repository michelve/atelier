# Prints the WebGL renderer Chromium reports, to confirm GPU (ANGLE/D3D11) rather than SwiftShader.
from playwright.sync_api import sync_playwright

JS = """() => {
  const gl = document.createElement('canvas').getContext('webgl2');
  if (!gl) return 'no webgl2';
  const ext = gl.getExtension('WEBGL_debug_renderer_info');
  return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
}"""

with sync_playwright() as p:
    # Headless Chromium defaults to software GL; these flags match what a headed agent browser gets.
    browser = p.chromium.launch(args=["--enable-gpu", "--use-angle=d3d11", "--ignore-gpu-blocklist"])
    page = browser.new_page()
    print(page.evaluate(JS))
    browser.close()
