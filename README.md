# Paint compiler for COLRv1 fonts

```sh
% paintcompiler --output "Example-Color.ttf" Example-Mono.ttf
```

There's a huge amount of very clever and pretty things you can do with the [COLRv1 font fonmat](https://github.com/googlefonts/colr-gradients-spec/blob/main/OFF_AMD2_WD.md). However, most font editors only expose a very small subset of the capabilities of the format. This is largely because, due to the fact that COLRv1 is so rich and extensive, it's not easy to produce a user interface which exposes all the functionality in a flexible way.

`paintcompiler` is a Python library and command line tool which makes it (slightly) easier to add COLRv1 `COLR` and `CPAL` tables to your fonts, using all the features that the format has to offer. That's the positive side. The negative side is that you need to describe your COLRv1 paints as Python code.

COLRv1 describes color glyphs as a kind of tree structure. In `paintcompiler` these tree nodes are described using Python functions. For example, to say that the glyph `A` is made up of a red `square` glyph and a blue `circle` glyph, you would say:

```python
glyphs["A"] = PaintColrLayers([
    PaintGlyph("square", PaintSolid("#FF0000FF")),
    PaintGlyph("circle", PaintSolid("#0000FFFF"))
])
```

The full interface is described below. See the example in `example/paints.py` for a paint file which exercises all paints.

## Using `paintcompiler`

To use `paintcompiler`, you need to write a *paint definition file*. This is a Python program which specifies which paints are applied to each glyph. `paintcompiler` will call your Python program in an environment with certain variables predefined. Your job is to fill the `glyphs` dictionary with the result of certain `Paint...()` function calls. In the example above, we call `PaintColorLayers` to define our top-level paint, and associate this with the `A` glyph.

As well as the `glyphs` dictionary and the `Paint...()` (and `ColorLine`/`VarColorLine`) functions, `paintcompiler` also provides the `font` variable, which is a `fontTools.ttLib.TTFont` object representing the font. This means you can query the font and define your paints programmatically. For example:

```python
SOLIDRED = PaintSolid("#FF0000FF")
BLUEDOT = PaintGlyph("dot", PaintSolid("#0000FFFF"))

for glyphname in font.getGlyphOrder():
    advancewidth = font["hmtx"][glyphname][0]
    glyphs[glyphname] = PaintColrLayers(
        # Paint the glyph in red
        PaintGlyph(glyphname, SOLIDRED),
        # Put a blue dot in the bottom right corner of the glyph
        PaintTranslate(advancewidth - 100, -100, BLUEDOT)
    )
```

Typically the paint definition file is called `paints.py`. If not, you can use the `-p`/`--paints` flag on the command line to specify a different name.

## Using `paintdecompiler`

If you have an *existing* COLRv1 font and you want to turn it back into a Python definition (paints file), you can use the `paintdecompiler` utility included with this module to do this. It is not smart enough to e.g. extract shared colorlines or variations into a Python variable, but it should get you started.

```
$ paintdecompiler example/COLRv1-Test.ttf
Written on paints.py
$ head paints.py
glyphs["p1_PaintColrLayers"] = PaintColrLayers(
    [
        PaintGlyph("square", PaintSolid("#EA4335FF")),
        PaintGlyph("circle", PaintSolid("#4285F4FF")),
    ],
)
glyphs["p2_PaintSolid"] = PaintGlyph("square", PaintSolid("#EA4335FF"))
...
```

## Variation specifications

You can create *variable* paints by passing a *variation specification* to the paint function. This variation specification describes how the values to the paint functions vary at different positions in the designspace, and is made up of a dictionary mapping a tuple of axis/location pairs to a value. For example, to create a glyph which rotates -180 degrees when the `ROTA` axis is at -1.0 and rotates 359 degrees when the `ROTA` axis is at 2.0, do this:

```python
PaintRotate(
    {
        (("ROTA", -1.0),): -180,
        (("ROTA", 2.0),): 359,
    },
    PaintGlyph("square", PaintSolid("#FF0000FF"))
)
```

*Notice* that the method here is `PaintRotate`. You *can* also call `PaintVarRotate`, but the compiler knows that this has a variation specifier, and so should be upgraded to a variable rotation.

(A variation specification can also be written as a variable-FEA-like string `"ROTA=-1.0:-180 ROTA=2.0:359"`, but that's deprecated and you'll get a warning.)

You can specify multiple axes in your variation specification by adding more axis/location pairs to the tuple:

```python
PaintRotate(
    {
        (("ROTX", -1.0), ("ROTY", -1.0)): -180,
        (("ROTX", -1.0), ("ROTY",  0.0)): -90,
        (("ROTX",  2.0), ("ROTY",  0.0)): -90,
        (("ROTX",  2.0), ("ROTY", -1.0)): -359,
    },
    PaintGlyph("square", PaintSolid("#FF0000FF"))
)
```

## Adding synthetic axes

When adding variable paints, you might want to add additional variation axes to your font - in other words, the axes only control the variable paints, and so aren't present when the font is compiled as a non-color font. `fontcompiler` provides the `--add-axis` command line flag to add one or more axes to your font:

```sh
$ paintcompiler \
    --add-axis "ALPH:0:0.5:1:Alpha value" \
    --add-axis "STAX:0:0:1000:Start X coordinate" \
    --add-axis "STAY:0:0:1000:Start Y coordinate" \
    --output "Example-Color.ttf" \
    Example-Mono.ttf
```

Now let's look at the functions that are available.

## Paint Functions

```python
PaintColrLayers(paints)
```

Stacks a number of paints together. `paints` should be an array of paints returned from other paint functions.

```python
PaintSolid(color_or_colors, alpha=1.0)
```

Creates a solid color paint, with the (potentially varying) given alpha value. A *color string* must be either an eight digit hex RGBA value, or the string `foreground` to specify the current ink color in the user's application. `color_or_colors` is either a single color string or, to give the user a choice of different color palettes, a Python list of color strings. The `alpha` parameter can either be a float from 0.0 to 1.0 or a *variation specification* as described above.

```python
PaintLinearGradient(
    (start_x, start_y),
    (end_x, end_y),
    (rot_x, rot_y),
    colorline
)
```

Creates a linear gradient which starts and ends and the given co-ordinates, and is rotated around the `rot_x`,`rot_y` coordinate. Any of the coordinates may either be floats or *variation specifications*. 

The colors on the gradient are specified using a `ColorLine`, as described below:

```python
ColorLine(stops, extend="pad")
ColorLine(start_stop, end_stop, extend="pad")
```

A color line can be specified using a dictionary mapping positions along the gradient (from 0.0 to 1.0) to *stops*, where each stop is either a `color_or_colors` or a tuple `(color_or_colors, alpha)`; it may also be specified using two stops, in which case one is taken as the start and the other the end. Hence, the following calls are all equivalent:

```python
ColorLine({
    0.0: ("#FF0000FF", 1.0),
    1.0: ("#00FF00FF", 1.0)
})
ColorLine({0.0: "#FF0000FF", 1.0: "#00FF00FF"})
ColorLine("#FF0000FF", "#00FF00FF")
```

The alpha value of a stop may vary, to make a variable color line:

```python
ALPHA_AXIS = { (("ALPH", 0.0),): 0.0, (("ALPH", 1.0),): 1.0 }
PaintLinearGradient(
    (0, 0), (1000, 1000), (0, 1000),
    ColorLine(
        {
            0.0: "#FF0000FF",
            0.5: ("#0000FFFF", ALPHA_AXIS),
            1.0: "#00FF00FF"
        }
    )
)
```

and the position of a stop may also vary, in which case a *list of tuples* must be used as a parameter to `ColorLine` instead of a dictionary:

```python
STOP_AXIS = { (("STOP", 0.0),): 0.0, (("STOP", 1.0),): 0.8 }
ALPHA_AXIS = { (("ALPH", 0.0),): 0.0, (("ALPH", 1.0),): 1.0 }

PaintLinearGradient(
    (0, 0), (1000, 1000), (0, 1000),
    ColorLine([
            (STOP_AXIS, "#FF0000FF"),
            (1.0, ("#00FF00FF", ALPHA_AXIS))
    ])
)
```

The *extend mode* of a `ColorLine` can be `pad`, `repeat` or `reflect`.


```python
PaintRadialGradient(
    (pt0_x, pt0_y),
    radius_0,
    (pt1_x, pt1_y),
    radius_1,
    colorline
)
```

Creates a radial gradient made up of the cylinder defined by two circles, the first centered at `pt0_x, pt0_y` with radius `radius_0` and the second centered at `pt1_x, pt1_y` with radius `radius_1`. Any of the coordinates and either of the radii may either be floats or *variation specifications*. 

```python
PaintSweepGradient((pt_x, pt_y), start_angle, end_angle, colorline)
```

Creates a sweep gradient centered at `pt_x, pt_y` made up of the arc between `start_angle` and `end_angle`. Any of the coordinates and either of the angles may either be floats or *variation specifications*. 

```python
PaintGlyph(glyph, paint)
```

Uses a (non-color) glyph's outline to mask the drawing of the given paint specification. For example, `PaintGlyph("A", PaintSolid("#FF0000FF"))` will use the shape of the letter "A" to mask out a solid red paint; the effect of this is to draw the letter in red. But `PaintGlyph("B", PaintGlyph("A", PaintSolid("#FF0000FF"))` uses the shape of the letter "B" as a mask to further mask out the painting; the effect of this is to draw the overlap between the A and the B outlines in red.

```python
PaintColrGlyph(glyph, paint=None)
```

Re-uses a color glyph's definition, either to paint it, or as a mask to mask another paint.

```python
PaintTransform([xx, xy, yx, yy, dx, dy], paint)
```

Transforms the given paint using an affine matrix. Any of the matrix elements may either be floats or *variation specifications*. 

```python
PaintTranslate(dx, dy, paint)
```

Translates the given paint in X and Y dimensions. Any of the translation coordinates may either be floats or *variation specifications*.

```python
PaintScale(scale_x, scale_y, paint, center=(pt_x, pt_y))
PaintScale(scale_x, paint, center=(pt_x, pt_y))
PaintScale(scale_x, scale_y, paint)
PaintScale(scale_x, paint)
```

Scales the given paint in X and Y dimensions. Any of the scale factors or the center coordinates may either be floats or *variation specifications*. If `scale_y` is not specified, a uniform scale is assumed. If the center is not specified, the scaling is performed around the origin.

```python
PaintRotate(angle, paint, center=(pt_x, pt_y))
PaintRotate(angle, paint)
```

Rotates the paint the given angle. The angle and/or the center coordinates may either be floats or *variation specifications*. If the center is not specified, the rotation is performed around the origin.

```python
PaintSkew(angle_x, angle_y, paint, center=(pt_x, pt_y))
PaintSkew(angle_x, angle_y, paint)
```

Skews the paint the given angles in X and Y dimensions. Any of the angles and/or the center coordinates may either be floats or *variation specifications*. If the center is not specified, the skewing is performed around the origin.

```python
PaintComposite(mode, src_paint, dst_paint)
```

Composites the source paint onto the destination paint. `mode` must be one of `'clear', 'src', 'dest', 'src_over', 'dest_over', 'src_in', 'dest_in', 'src_out', 'dest_out', 'src_atop', 'dest_atop', 'xor', 'plus', 'screen', 'overlay', 'darken', 'lighten', 'color_dodge', 'color_burn', 'hard_light', 'soft_light', 'difference', 'exclusion', 'multiply', 'hsl_hue', 'hsl_saturation', 'hsl_color', 'hsl_luminosity'`.

## Why not just use `fontTools.colorLib.builder`?

`paintcompiler` does use the fontTools color builder underneath to construct the COLR tables, but it adds a few helpful facilities on top:

* `paintcompiler` provides a command line interface to add COLR tables. This command line interface allows adding synthetic axes.

* Color palettes are built automatically, so you don't have to assign each color to an index and carry that index around - just specify the color directly. (You can still specify user-selected alternate color palettes by writing the color as an array of options.)

* In `paintcompiler`, paint operations are functions; this makes the syntax considerably less verbose and easier to follow. Compare

```python
PaintColrLayers([
    PaintGlyph("square", PaintSolid("#FF0000FF")),
    PaintGlyph("circle", PaintSolid("#0000FFFF"))
])
```

versus

```python
(
    ot.PaintFormat.PaintColrLayers,
    [
        {
            "Format": ot.PaintFormat.PaintGlyph,
            "Paint": {
                "Format": ot.PaintFormat.PaintSolid,
                "PaletteIndex": 1,
                "Alpha": 1.0,
            },
            "Glyph": "square",
        },
        {
            "Format": ot.PaintFormat.PaintGlyph,
            "Paint": {
                "Format": ot.PaintFormat.PaintSolid,
                "PaletteIndex": 2,
                "Alpha": 1.0,
            },
            "Glyph": "circle",
        },
    ]
)
```

* `colorLib.builder` does not provide any help when specifying variable paints; you have to keep track of the `VarIndexBase` and populate the variation store yourself. In `paintcompiler`, you can specify how a paint varies directly, and the variation table gets built for you.

* `colorLib.builder` requires you to explicitly choose the appropriate paint representation. `paintcompiler` uses the parameters to work out the correct paint format; a single `PaintScale` function allows access to `PaintScale`, `PaintVarScale`, `PaintScaleAroundCenter`, `PaintVarScaleAroundCenter`, `PaintScaleUniform`, `PaintVarScaleUniform`, `PaintScaleUniformAroundCenter` and `PaintVarScaleUniformAroundCenter`. This greatly reduces the number of functions that you need to worry about.
