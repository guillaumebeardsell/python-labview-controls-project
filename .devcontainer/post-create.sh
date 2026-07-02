#!/bin/bash
# Post-create setup beyond pip: system packages used to render and verify
# the invention-disclosure deliverables (docx -> PDF -> PNG checks).
#   libreoffice-writer        soffice --headless --convert-to pdf <file>
#   poppler-utils             pdftoppm page rasterization
#   fonts-crosextra-carlito   metric stand-in for Aptos (not on Linux)
set -e

sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    libreoffice-writer poppler-utils fonts-crosextra-carlito

# Map the documents' Aptos font to Carlito so LibreOffice renders with
# near-faithful metrics (page counts / line breaks close to Word's).
mkdir -p ~/.config/fontconfig
cat > ~/.config/fontconfig/fonts.conf <<'XML'
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <match target="pattern">
    <test qual="any" name="family"><string>Aptos</string></test>
    <edit name="family" mode="assign" binding="same"><string>Carlito</string></edit>
  </match>
</fontconfig>
XML
fc-cache -f >/dev/null
echo "post-create: LibreOffice render toolchain ready"
