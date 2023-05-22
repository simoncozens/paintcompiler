#!/bin/sh
fontmake -o variable -g COLRv1-Test.glyphs --no-production-names
paintcompiler \
    --add-axis "ALPH:0:0.5:1:Alpha value" \
    --add-axis "STAX:0:0:1000:Start X coordinate" \
    --add-axis "STAY:0:0:1000:Start Y coordinate" \
    --add-axis "ENDX:0:1000:1000:End X coordinate" \
    --add-axis "ENDY:0:1000:1000:End Y coordinate" \
    --add-axis "ROTX:0:200:1000:Center of rotation X coordinate" \
    --add-axis "ROTY:0:200:1000:Center of rotation Y coordinate" \
    --add-axis "STAR:0:100:500:Start radius" \
    --add-axis "ENDR:0:400:500:End radius" \
    --add-axis "STAA:-359:-90:359:Start angle" \
    --add-axis "ENDA:-359:330:359:End angle" \
    --add-axis "TRAX:-500:0:500:Translate X coordinate" \
    --add-axis "TRAY:-500:0:500:Translate Y coordinate" \
    --add-axis "SCLX:-1.99:1:1.99:Scale X" \
    --add-axis "SCLY:-1.99:1:1.99:Scale Y" \
    --add-axis "SCXY:-1.99:0:1.99:Scale XY" \
    --add-axis "SCYX:-1.99:0:1.99:Scale YX" \
    --output COLRv1-Test.ttf \
    --paints paints.py \
    variable_ttf/COLRv1TestFont-Regular-VF.ttf
