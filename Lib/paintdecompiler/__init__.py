from fontTools.ttLib import TTFont
import sys
from fontTools.colorLib.unbuilder import unbuildColrV1
from fontTools.ttLib.tables.otTables import PaintFormat
from black import format_file_contents, Mode
from fontTools.misc.fixedTools import (
    floatToFixedToStr,
    fixedToFloat,
    floatToFixedToFloat,
)
import re

angle_convertor = lambda x: fixedToFloat(x, 14) * 180
f2dot14_convertor = lambda x: fixedToFloat(x, 14)
fixed_converter = lambda x: fixedToFloat(x, 16)


def region_tuple(region, fvar):
    s = []
    for axis, reg in zip(fvar.axes, region.VarRegionAxis):
        if reg.StartCoord == reg.PeakCoord == reg.EndCoord:
            continue
        s.append(axis.axisTag + "=" + str(reg.PeakCoord))  # Hack? But probably works
    return ", ".join(s)


def list_get(l, i, default=None):
    try:
        return l[i]
    except IndexError:
        return default


class PythonUnbuilder:
    def __init__(self, palettes, table, fvar=None, precision=14) -> None:
        self.palettes = palettes
        self.variations = table.VarStore
        self.varindexmap = table.VarIndexMap
        self.fvar = fvar
        self.precision = precision

    def get_variations(self, paint, names, base_element=0, convertor=None):
        return {
            name: self.get_variation(paint, base_element + ix, name, convertor)
            for ix, name in enumerate(names)
        }

    def get_variation(self, paint, element, name, convertor=None):
        if convertor is None:
            convertor = lambda x: x
        base_value = paint.get(name)
        if "VarIndexBase" not in paint:
            return base_value
        index = paint["VarIndexBase"] + element
        if index == 4294967295:
            return base_value
        mapping = self.varindexmap.mapping[index]
        if mapping == 4294967295:
            return base_value
        outer, inner = mapping >> 16, mapping & 0xFFFF
        vardata = self.variations.VarData[outer]
        regions = [
            region_tuple(self.variations.VarRegionList.Region[ix], self.fvar)
            for ix in vardata.VarRegionIndex
        ]
        data = vardata.Item[inner]
        if not regions or not data:
            return base_value
        variations = {"": base_value}
        for r, d in zip(regions, data):
            variations[r] = base_value + convertor(d)
        return variations

    def color2py(self, index):
        cols = ['"' + str(list_get(pal, index, "None")) + '"' for pal in self.palettes]
        if len(cols) > 1:
            return f"[{', '.join(cols)}]"
        return cols[0]

    def colorstop2py(self, colorstop, offset=True):
        rv = ""
        if offset:
            rv += (
                self._tidy(
                    self.get_variation(
                        colorstop, 0, "StopOffset", lambda r: fixedToFloat(r, 14)
                    )
                )
                + ":"
            )
        alpha = self.get_variation(colorstop, 1, "Alpha", lambda r: fixedToFloat(r, 14))
        if alpha != 1.0:
            rv += "{"
            rv += f"color: {self.color2py(colorstop['PaletteIndex'])},"
            rv += f"alpha: {self._tidy(alpha)},"
            rv += "}"
        else:
            rv += self.color2py(colorstop["PaletteIndex"])
        return rv

    def colorline2py(self, colorline):
        if (
            len(colorline["ColorStop"]) == 2
            and colorline["ColorStop"][0]["StopOffset"] == 0.0
            and colorline["ColorStop"][1]["StopOffset"] == 1.0
        ):
            stop = (
                self.colorstop2py(colorline["ColorStop"][0], offset=False)
                + ", "
                + self.colorstop2py(colorline["ColorStop"][1], offset=False)
            )
        else:
            stop = (
                "{"
                + ",".join(self.colorstop2py(stop) for stop in colorline["ColorStop"])
                + "}"
            )
        extend = ""
        if colorline["Extend"] != "pad":
            extend = 'extend="' + colorline.get("Extend") + '"'
        return f"ColorLine({stop}, {extend})"

    def _tidy(self, number):
        if isinstance(number, float):
            return floatToFixedToStr(number, self.precision)
        return str(number)

    def _format(self, paint, pattern, variable=False):
        return re.sub(r"\w+", lambda w: self._tidy(paint.get(w[0])), pattern)

    def PaintColrLayers_args(self, paint):
        rv = ", ".join([self.paint2py(x) for x in paint["Layers"]])
        return f"[{rv}],"

    def PaintSolid_args(self, paint):
        rv = self.color2py(paint["PaletteIndex"])
        if paint["Alpha"] != 1.0:
            rv += f", alpha={self._tidy(paint['Alpha'])}"
        return rv

    def PaintVarSolid_args(self, paint):
        rv = self.color2py(paint["PaletteIndex"])
        alpha = self.get_variation(paint, 0, "Alpha", lambda r: fixedToFloat(r, 14))
        if alpha != 1.0:
            rv += f", alpha={self._tidy(alpha)}"
        return rv

    def PaintLinearGradient_args(self, paint):
        return self._format(
            paint, "(x0, y0), (x1, y1), (x2, y2), "
        ) + self.colorline2py(paint["ColorLine"])

    def PaintVarLinearGradient_args(self, paint):
        p = self.get_variations(paint, ["x0", "y0", "x1", "y1", "x2", "y2"])
        return self._format(p, "(x0, y0), (x1, y1), (x2, y2), ") + self.colorline2py(
            paint["ColorLine"]
        )

    def PaintRadialGradient_args(self, paint):
        return self._format(paint, "(x0, y0), r0, (x1, y1), r1, ") + self.colorline2py(
            paint["ColorLine"]
        )

    def PaintVarRadialGradient_args(self, paint):
        p = self.get_variations(paint, ["x0", "y0", "r0", "x1", "y1", "r1"])
        return self._format(p, "(x0, y0), r0, (x1, y1), r1, ") + self.colorline2py(
            paint["ColorLine"]
        )

    def PaintSweepGradient_args(self, paint):
        return self._format(
            paint, "(centerX, centerY), startAngle, endAngle,"
        ) + self.colorline2py(paint["ColorLine"])

    def PaintVarSweepGradient_args(self, paint):
        p = self.get_variations(paint, ["centerX", "centerY"]) | self.get_variations(
            paint, ["startAngle", "endAngle"], base_element=2, convertor=angle_convertor
        )
        return self._format(
            p, "(centerX, centerY), startAngle, endAngle,"
        ) + self.colorline2py(paint["ColorLine"])

    def PaintGlyph_args(self, paint):
        rv = '"' + paint.get("Glyph") + '", '
        return rv

    def PaintColrGlyph_args(self, paint):
        rv = '"' + paint.get("Glyph") + '", '
        return rv

    def PaintTransform_args(self, paint):
        rv = self._format(paint.get("Transform"), "(xx, yx, xy, yy, dx, dy), ")
        return rv

    def PaintVarTransform_args(self, paint):
        p = self.get_variations(
            paint["Transform"],
            ["xx", "yx", "xy", "yy", "dx", "dy"],
            convertor=fixed_converter,
        )
        rv = self._format(p, "(xx, yx, xy, yy, dx, dy), ")
        return rv

    def PaintTranslate_args(self, paint):
        rv = self._format(paint, "dx, dy,")
        return rv

    def PaintVarTranslate_args(self, paint):
        p = self.get_variations(
            paint,
            ["dx", "dy"],
        )
        rv = self._format(p, "dx, dy,")
        return rv

    def PaintComposite_args(self, paint):
        rv = self.paint2py(paint["SourcePaint"])
        if paint.get("BackdropPaint"):
            rv += ", " + self.paint2py(paint["BackdropPaint"])
        if paint.get("CompositeMode") and paint["CompositeMode"] != "dest_over":
            rv += f", mode='{paint['CompositeMode']}'"
        return rv

    def PaintScale_args(self, paint):
        return self._format(paint, "scaleX, scaleY,")

    def PaintVarScale_args(self, paint):
        p = self.get_variations(
            paint, ["scaleX", "scaleY"], convertor=f2dot14_convertor
        )
        return self._format(p, "scaleX, scaleY,")

    def PaintScaleAroundCenter_args(self, paint):
        return self._format(paint, "scaleX, scaleY, (centerX, centerY),")

    def PaintVarScaleAroundCenter_args(self, paint):
        p = self.get_variations(
            paint, ["scaleX", "scaleY"], convertor=f2dot14_convertor
        ) | self.get_variations(paint, ["centerX", "centerY"], base_element=2)
        return self._format(p, "scaleX, scaleY, (centerX, centerY), ")

    def PaintScaleUniform_args(self, paint):
        return self._format(paint, "scale,")

    def PaintVarScaleUniform_args(self, paint):
        scale_variation = self.get_variation(
            paint,
            0,
            "scale",
            lambda l: floatToFixedToFloat(fixedToFloat(l, 14), self.precision),
        )
        return str(scale_variation) + ","

    def PaintScaleUniformAroundCenter_args(self, paint):
        return self._format(paint, "scale, (centerX, centerY),")

    def PaintVarScaleUniformAroundCenter_args(self, paint):
        p = self.get_variations(
            paint, ["scale"], convertor=f2dot14_convertor
        ) | self.get_variations(paint, ["centerX", "centerY"], base_element=1)
        return self._format(p, "scale, (centerX, centerY), ")

    def PaintRotate_args(self, paint):
        return self._tidy(paint["angle"]) + ","

    def PaintVarRotate_args(self, paint):
        p = self.get_variations(paint, ["angle"], convertor=angle_convertor)
        return self._format(p, "angle, ")

    def PaintRotateAroundCenter_args(self, paint):
        return self._format(paint, "angle, (centerX, centerY),")

    def PaintVarRotateAroundCenter_args(self, paint):
        p = self.get_variations(
            paint, ["angle"], convertor=angle_convertor
        ) | self.get_variations(paint, ["centerX", "centerY"], base_element=1)
        return self._format(p, "angle, (centerX, centerY), ")

    def PaintSkew_args(self, paint):
        return self._format(paint, "xSkewAngle, ySkewAngle,")

    def PaintVarSkew_args(self, paint):
        p = self.get_variations(
            paint, ["xSkewAngle", "ySkewAngle"], convertor=angle_convertor
        )
        return self._format(p, "xSkewAngle, ySkewAngle,")

    def PaintSkewAroundCenter_args(self, paint):
        return self._format(paint, "xSkewAngle, ySkewAngle, (centerX, centerY), ")

    def PaintVarSkewAroundCenter_args(self, paint):
        p = self.get_variations(
            paint, ["xSkewAngle", "ySkewAngle"], convertor=angle_convertor
        ) | self.get_variations(paint, ["centerX", "centerY"], base_element=2)
        return self._format(p, "xSkewAngle, ySkewAngle, (centerX, centerY), ")

    def paint2py(self, paint):
        pformat = PaintFormat(paint["Format"])
        if hasattr(self, pformat.name + "_args"):
            rv = pformat.name + "(" + getattr(self, pformat.name + "_args")(paint)
        else:
            rv = pformat.name + "(NotImplemented, "
        if paint.get("Paint"):
            rv += self.paint2py(paint["Paint"])
        rv += ")"
        return rv


def main(args=None):
    import argparse

    parser = argparse.ArgumentParser(description="Decompile COLR table to paints.py")
    parser.add_argument("font", metavar="TTF", help="a font to decompile")
    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        metavar="PY",
        default="paints.py",
        help="Python file to emit (default: paints.py)",
    )

    args = parser.parse_args(args)
    font = TTFont(args.font)
    if not "COLR" in font:
        print("No COLR table")
        sys.exit(1)

    colr = font["COLR"].table
    if colr.Version == 0:
        print("COLR version is not 1")
        sys.exit(1)

    colorGlyphs = unbuildColrV1(
        colr.LayerList,
        colr.BaseGlyphList,
    )
    palettes = font["CPAL"].palettes
    unbuilder = PythonUnbuilder(
        palettes, table=colr, fvar=font.get("fvar"), precision=14
    )

    output = ""
    for glyph, description in colorGlyphs.items():
        line = f"glyphs['{glyph}'] = {unbuilder.paint2py(description)}\n"
        try:
            line = format_file_contents(line, fast=True, mode=Mode(line_length=78))
        except:
            pass
        output += line

    with open(args.output, "w") as fh:
        fh.write(output)

    print(f"Written on {args.output}")


if __name__ == "__main__":
    main()
