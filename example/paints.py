BLUE = "#4285F4FF"
GREEN = "#34A853FF"
RED = "#EA4335FF"


ax = {}

for axis in font["fvar"].axes:
    tag = axis.axisTag
    ax[tag] = {
        ((tag, axis.minValue),): axis.minValue,
        ((tag, axis.defaultValue),): axis.defaultValue,
        ((tag, axis.maxValue),): axis.maxValue,
    }

RGB_COLORLINE = ColorLine({0: RED, 0.5: GREEN, 1.0: BLUE})
VAR_COLORLINE = ColorLine({0: RED, 0.5: (GREEN, ax["ALPH"]), 1.0: BLUE})

REDSQUARE = PaintGlyph("square", PaintSolid(RED))
BLUESQUARE = PaintGlyph("square", PaintSolid(BLUE))
BLUECIRCLE = PaintGlyph("circle", PaintSolid(BLUE))
GREENSTAR = PaintGlyph("star", PaintSolid(GREEN))

staa = {
    (("STAA", -180),): -180,
    (("STAA", 359),): 359,
}
enda = {
    (("ENDA", -180),): -180,
    (("ENDA", 359),): 359,
}


def make_coord_axis(tag):
    # fmt: off
    return {
      ((tag, 0, ), ): 0,
      ((tag, 1000, ), ): 1000,
    }
    # fmt: on


stax = make_coord_axis("STAX")
stay = make_coord_axis("STAY")
endx = make_coord_axis("ENDX")
endy = make_coord_axis("ENDY")
rotx = make_coord_axis("ROTX")
roty = make_coord_axis("ROTY")

glyphs["p1_PaintColrLayers"] = PaintColrLayers(
    [
        REDSQUARE,
        BLUECIRCLE,
    ]
)

glyphs["p2_PaintSolid"] = REDSQUARE

glyphs["p3_PaintVarSolid"] = PaintGlyph(
    "square",
    PaintSolid(
        RED,
        ax["ALPH"],
    ),
)

glyphs["p4_PaintLinearGradient"] = PaintGlyph(
    "square",
    PaintLinearGradient((0, 100), (600, 200), (0, 0), RGB_COLORLINE),
)


glyphs["p5_PaintVarLinearGradient"] = PaintGlyph(
    "square",
    PaintLinearGradient(
        (ax["STAX"], ax["STAY"]),
        (ax["ENDX"], ax["ENDY"]),
        (ax["ROTX"], ax["ROTY"]),
        VAR_COLORLINE,
    ),
)


glyphs["p6_PaintRadialGradient"] = PaintGlyph(
    "square",
    PaintRadialGradient((350, 200), 100, (350, 800), 300, RGB_COLORLINE),
)

glyphs["p7_PaintVarRadialGradient"] = PaintGlyph(
    "square",
    PaintRadialGradient(
        (ax["STAX"], ax["STAY"]),
        ax["STAR"],
        (ax["ENDX"], ax["ENDY"]),
        ax["ENDR"],
        VAR_COLORLINE,
    ),
)

glyphs["p8_PaintSweepGradient"] = PaintGlyph(
    "circle",
    PaintSweepGradient((350, 350), 0, 250, RGB_COLORLINE),
)

glyphs["p9_PaintVarSweepGradient"] = PaintGlyph(
    "circle",
    PaintSweepGradient((350, 350), ax["STAA"], ax["ENDA"], VAR_COLORLINE),
)

glyphs["p10_PaintGlyph"] = PaintGlyph("circle", GREENSTAR)
glyphs["p11_PaintColrGlyph"] = PaintColrGlyph("p10_PaintGlyph")

glyphs["p12_PaintTransform"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintTransform(
            (1.1, 0.3, 0.4, 0.8, 100, -50),
            BLUESQUARE,
        ),
    ]
)

glyphs["p13_PaintVarTransform"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintTransform(
            (ax["SCLX"], ax["SCXY"], ax["SCYX"], ax["SCLY"], ax["TRAX"], ax["TRAY"]),
            BLUESQUARE,
        ),
    ]
)


glyphs["p14_PaintTranslate"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintTranslate(100, 100, BLUESQUARE),
    ]
)

glyphs["p15_PaintVarTranslate"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintTranslate(ax["TRAX"], ax["TRAY"], BLUESQUARE),
    ]
)


glyphs["p16_PaintScale"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintScale(1.2, 0.8, BLUESQUARE),
    ]
)

glyphs["p17_PaintVarScale"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintScale(ax["SCLX"], ax["SCLY"], BLUESQUARE),
    ]
)

glyphs["p18_PaintScaleAroundCenter"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintScale(1.2, 0.8, (300, 200), BLUESQUARE),
    ]
)

glyphs["p19_PaintVarScaleAroundCenter"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintScale(
            ax["SCLX"], ax["SCLY"], (ax["STAX"], ax["STAY"]), BLUESQUARE
        ),
    ]
)

glyphs["p20_PaintScaleUniform"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintScale(0.8, BLUESQUARE),
    ]
)

glyphs["p21_PaintVarScaleUniform"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintScale(ax["SCLX"], BLUESQUARE),
    ]
)

glyphs["p22_PaintScaleUniformAroundCenter"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintScale(0.8, BLUESQUARE, center=(300, 250)),
    ]
)

glyphs["p23_PaintVarScaleUniformAroundCenter"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintScale(
            ax["SCLX"], BLUESQUARE, center= (ax["STAX"], ax["STAY"])
        ),
    ]
)

glyphs["p24_PaintRotate"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintRotate(-15, BLUESQUARE),
    ]
)

glyphs["p25_PaintVarRotate"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintRotate(ax["STAA"], BLUESQUARE),
    ]
)

glyphs["p26_PaintRotateAroundCenter"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintRotate(-15, (300, 250), BLUESQUARE),
    ]
)

glyphs["p27_PaintVarRotateAroundCenter"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintRotate(ax["STAA"], (ax["STAX"], ax["STAY"]), BLUESQUARE),
    ]
)

glyphs["p28_PaintSkew"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintSkew(-15, 10, BLUESQUARE),
    ]
)

glyphs["p29_PaintVarSkew"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintSkew(ax["STAA"], ax["ENDA"], BLUESQUARE),
    ]
)


glyphs["p30_PaintSkewAroundCenter"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintSkew(-15, 10, BLUESQUARE, center=(350, 200)),
    ]
)

glyphs["p31_PaintVarSkewAroundCenter"] = PaintColrLayers(
    [
        REDSQUARE,
        PaintSkew(
            ax["STAA"], ax["ENDA"], BLUESQUARE, center=(ax["STAX"], ax["STAY"])
        ),
    ]
)

glyphs["p32_PaintComposite"] = PaintComposite(
    "multiply",
    PaintComposite("dest_out", GREENSTAR, BLUECIRCLE),
    REDSQUARE,
)
