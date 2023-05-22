import logging
from fontTools.ttLib import TTFont
from fontTools.colorLib.builder import buildCOLR, buildCPAL
from fontTools.ttLib.tables.otTables import CompositeMode
from fontTools.varLib.varStore import OnlineVarStoreBuilder
from fontTools.varLib.builder import buildDeltaSetIndexMap
from fontTools.feaLib.variableScalar import VariableScalar
from fontTools.misc.fixedTools import floatToFixed, fixedToFloat
from fontTools.ttLib.tables._f_v_a_r import Axis


def compile_color(c):
    return tuple(int(x, 16) / 255 for x in [c[1:3], c[3:5], c[5:7], c[7:9]])


def compile_colors(colors):
    return [compile_color(c) for c in colors]


class ColorLine:
    def __init__(self, start_or_stops, end=None, extend="pad"):
        if end is None:
            stops = start_or_stops
        else:
            stops = {0.0: start_or_stops, 1.0: end}
        self.colorstops = []
        self.needs_variable = False
        self.extend = extend
        if isinstance(stops, dict):
            stops = list(stops.items())
        for k, v in stops:
            alpha = 1.0
            if isinstance(v, (list, tuple)):
                alpha = v[1]
                v = v[0]
            if isinstance(alpha, (dict, str)):
                self.needs_variable = True
            self.colorstops.append((k, v, alpha))

    def compile(self, compiler):
        if self.needs_variable:
            return self.compile_var(compiler)
        return {
            "Extend": self.extend,
            "ColorStop": [
                {
                    "StopOffset": k,
                    "Alpha": alpha,
                    "PaletteIndex": compiler.get_palette_index(v),
                }
                for (k, v, alpha) in self.colorstops
            ],
        }

    def compile_var(self, compiler):
        obj = {"Extend": self.extend, "ColorStop": []}
        for k, v, alpha in self.colorstops:
            base = len(compiler.deltaset)
            obj["ColorStop"].append(
                {
                    "StopOffset": compiler.prepare_variable(k, units="f2dot14"),
                    "Alpha": compiler.prepare_variable(alpha, units="f2dot14"),
                    "PaletteIndex": compiler.get_palette_index(v),
                    "VarIndexBase": base,
                }
            )
        return obj


def is_variable(thing):
    if isinstance(thing, ColorLine):
        return thing.needs_variable
    return isinstance(thing, (str, dict))


def any_variable(*things):
    return any(is_variable(x) for x in things)


class PythonBuilder:
    def __init__(self, font: TTFont) -> None:
        self.font = font
        self.palette = []
        self.variations = []
        self.deltaset: list[int] = []
        assert "fvar" in font, "Font needs an fvar table"
        self.axes = font["fvar"].axes
        axis_tags = [x.axisTag for x in self.axes]
        self.varstorebuilder = OnlineVarStoreBuilder(axis_tags)

    def make_var_scalar(self, s, units=None):
        converter = float
        if units == "f2dot14":
            converter = lambda x: floatToFixed(float(x), 14)
        elif units == "fixed":
            converter = lambda x: floatToFixed(float(x), 16)
        elif units == "angle":
            converter = lambda x: floatToFixed(float(x) / 180, 14)
        elif units is not None:
            raise ValueError(f"Unknown units {units}")
        v = VariableScalar()
        v.axes = self.axes
        default_location = {axis.axisTag: axis.defaultValue for axis in self.axes}
        if isinstance(s, (float, int)):
            v.add_value(default_location, converter(float(s)))
            return v

        first_value = None
        values_dict = {}

        if isinstance(s, str):
            for values in s.split():
                locations, value = values.split(":")
                location = {}
                for loc in locations.split(","):
                    axis, axis_loc = loc.split("=")
                    location[axis] = float(axis_loc)
                values_dict[tuple(location.items())] = value

            logging.warning(f"Consider using dict {values_dict} instead of string {s}")
        elif isinstance(s, dict):
            values_dict = s
        else:
            raise ValueError(f"Could not understand variable parameter {s}")

        for location, value in values_dict.items():
            if units != "fixed" and (converter(value) <= -32768 or converter(value) >= 32768):
                raise ValueError(f"Value too big in '{s}'")
            v.add_value(dict(location), converter(value))

            if first_value is None:
                first_value = value

        if not tuple(sorted(default_location.items())) in v.values:
            if first_value is None:
                raise ValueError(f"No default value OR first value in '{s}'")
            v.add_value(default_location, converter(first_value))
        return v

    def get_palette_index(self, color):
        if color == "foreground":
            return 0xFFFF
        if not isinstance(color, list):
            color = [color]
        if color not in self.palette:
            self.palette.append(color)
        return self.palette.index(color)

    def prepare_variable(self, value, units=None):
        vs = self.make_var_scalar(value, units=units)
        default, index = vs.add_to_variation_store(self.varstorebuilder)
        self.deltaset.append(index)
        if units == "f2dot14":
            return fixedToFloat(default, 14)
        elif units == "angle":
            return fixedToFloat(default, 14) * 180
        elif units == "fixed":
            return fixedToFloat(default, 16)
        elif units is not None:
            raise ValueError(f"Unknown units {units}")
        return default

    def PaintColrLayers(self, layers):
        return {"Format": 1, "Layers": layers}

    def PaintSolid(self, col_or_colrs, alpha=1.0):
        if is_variable(alpha):
            return self.PaintVarSolid(col_or_colrs, alpha)
        return {
            "Format": 2,
            "PaletteIndex": self.get_palette_index(col_or_colrs),
            "Alpha": alpha,
        }

    def PaintVarSolid(self, col_or_colrs, alpha):
        base = len(self.deltaset)
        alpha_def = self.prepare_variable(alpha, units="f2dot14")
        return {
            "Format": 3,
            "PaletteIndex": self.get_palette_index(col_or_colrs),
            "Alpha": alpha_def,
            "VarIndexBase": base,
        }

    def PaintLinearGradient(self, pt0, pt1, pt2, colorline):
        if any_variable(*pt0, *pt1, *pt2, colorline):
            return self.PaintVarLinearGradient(pt0, pt1, pt2, colorline)
        return {
            "Format": 4,
            "x0": pt0[0],
            "y0": pt0[1],
            "x1": pt1[0],
            "y1": pt1[1],
            "x2": pt2[0],
            "y2": pt2[1],
            "ColorLine": colorline.compile(self),
        }

    def PaintVarLinearGradient(self, pt0, pt1, pt2, colorline):
        base = len(self.deltaset)
        return {
            "Format": 5,
            "x0": self.prepare_variable(pt0[0]),
            "y0": self.prepare_variable(pt0[1]),
            "x1": self.prepare_variable(pt1[0]),
            "y1": self.prepare_variable(pt1[1]),
            "x2": self.prepare_variable(pt2[0]),
            "y2": self.prepare_variable(pt2[1]),
            "ColorLine": colorline.compile_var(self),
            "VarIndexBase": base,
        }

    def PaintRadialGradient(self, pt0, rad0, pt1, rad1, colorline):
        if any_variable(*pt0, rad0, *pt1, rad1, colorline):
            return self.PaintVarRadialGradient(pt0, rad0, pt1, rad1, colorline)
        return {
            "Format": 6,
            "x0": pt0[0],
            "y0": pt0[1],
            "r0": rad0,
            "x1": pt1[0],
            "y1": pt1[1],
            "r1": rad1,
            "ColorLine": colorline.compile(self),
        }

    def PaintVarRadialGradient(self, pt0, rad0, pt1, rad1, varcolorline):
        base = len(self.deltaset)
        return {
            "Format": 7,
            "x0": self.prepare_variable(pt0[0]),
            "y0": self.prepare_variable(pt0[1]),
            "r0": self.prepare_variable(rad0),
            "x1": self.prepare_variable(pt1[0]),
            "y1": self.prepare_variable(pt1[1]),
            "r1": self.prepare_variable(rad1),
            "ColorLine": varcolorline.compile_var(self),
            "VarIndexBase": base,
        }

    def PaintSweepGradient(self, pt, startAngle, endAngle, colorline):
        if any_variable(*pt, startAngle, endAngle, colorline):
            return self.PaintVarSweepGradient(pt, startAngle, endAngle, colorline)
        return {
            "Format": 8,
            "centerX": pt[0],
            "centerY": pt[1],
            "startAngle": startAngle,
            "endAngle": endAngle,
            "ColorLine": colorline.compile(self),
        }

    def PaintVarSweepGradient(self, pt, startAngle, endAngle, varcolorline):
        base = len(self.deltaset)
        return {
            "Format": 9,
            "centerX": self.prepare_variable(pt[0]),
            "centerY": self.prepare_variable(pt[1]),
            "startAngle": self.prepare_variable(startAngle, units="angle"),
            "endAngle": self.prepare_variable(endAngle, units="angle"),
            "ColorLine": varcolorline.compile_var(self),
            "VarIndexBase": base,
        }

    def PaintGlyph(self, glyph, paint=None):
        return {"Format": 10, "Glyph": glyph, "Paint": paint}

    def PaintColrGlyph(self, glyph, paint=None):
        return {"Format": 11, "Glyph": glyph}

    def PaintTransform(self, matrix, paint):
        if any_variable(*matrix):
            return self.PaintVarTransform(matrix, paint)
        return {
            "Format": 12,
            "Paint": paint,
            "Transform": {
                "xx": matrix[0],
                "xy": matrix[1],
                "yx": matrix[2],
                "yy": matrix[3],
                "dx": matrix[4],
                "dy": matrix[5],
            },
        }

    def PaintVarTransform(self, matrix, paint):
        base = len(self.deltaset)
        return {
            "Format": 13,
            "Paint": paint,
            "Transform": {
                "xx": self.prepare_variable(matrix[0], units="fixed"),
                "xy": self.prepare_variable(matrix[1], units="fixed"),
                "yx": self.prepare_variable(matrix[2], units="fixed"),
                "yy": self.prepare_variable(matrix[3], units="fixed"),
                "dx": self.prepare_variable(matrix[4], units="fixed"),
                "dy": self.prepare_variable(matrix[5], units="fixed"),
                "VarIndexBase": base,
            },
        }

    def PaintTranslate(self, dx, dy, paint):
        if any_variable(dx, dy):
            return self.PaintVarTranslate(dx, dy, paint)
        return {"Format": 14, "dx": dx, "dy": dy, "Paint": paint}

    def PaintVarTranslate(self, dx, dy, paint):
        base = len(self.deltaset)
        return {
            "Format": 15,
            "dx": self.prepare_variable(dx),
            "dy": self.prepare_variable(dy),
            "Paint": paint,
            "VarIndexBase": base,
        }

    def PaintScale(self, *args, scale_x=None, scale_y=None, center=None, paint=None):
        if paint is None and len(args) == 1:
            paint = args[0]
        elif paint is None and scale_x is None and len(args) == 2:
            scale_x, paint = args
        elif paint is None and scale_x is None and scale_y is None and len(args) == 3:
            scale_x, scale_y, paint = args
        elif (
            paint is None
            and scale_x is None
            and scale_y is None
            and center is None
            and len(args) == 4
        ):
            scale_x, scale_y, center, paint = args
        if paint is None or scale_x is None:
            raise ValueError("Couldn't understand arguments to PaintScale")
        if center is not None:
            if scale_y is not None:
                return self.PaintScaleAroundCenter(scale_x, scale_y, center, paint)
            else:
                return self.PaintScaleUniformAroundCenter(scale_x, center, paint)
        if scale_y is None:
            return self.PaintScaleUniform(scale_x, paint)

        if any_variable(scale_x, scale_y):
            return self.PaintVarScale(scale_x, scale_y, paint)
        return {
            "Format": 16,
            "scaleX": scale_x,
            "scaleY": scale_y,
            "Paint": paint,
        }

    def PaintVarScale(self, scale_x, scale_y, paint):
        base = len(self.deltaset)
        return {
            "Format": 17,
            "scaleX": self.prepare_variable(scale_x, units="f2dot14"),
            "scaleY": self.prepare_variable(scale_y, units="f2dot14"),
            "Paint": paint,
            "VarIndexBase": base,
        }

    def PaintScaleAroundCenter(self, scale_x, scale_y, center, paint):
        if any_variable(scale_x, scale_y, *center):
            return self.PaintVarScaleAroundCenter(scale_x, scale_y, center, paint)
        return {
            "Format": 18,
            "scaleX": scale_x,
            "scaleY": scale_y,
            "centerX": center[0],
            "centerY": center[1],
            "Paint": paint,
        }

    def PaintVarScaleAroundCenter(self, scale_x, scale_y, center, paint):
        base = len(self.deltaset)
        return {
            "Format": 19,
            "scaleX": self.prepare_variable(scale_x, units="f2dot14"),
            "scaleY": self.prepare_variable(scale_y, units="f2dot14"),
            "centerX": self.prepare_variable(center[0]),
            "centerY": self.prepare_variable(center[1]),
            "Paint": paint,
            "VarIndexBase": base,
        }

    def PaintScaleUniform(self, scale, paint):
        if any_variable(scale):
            return self.PaintVarScaleUniform(scale, paint)
        return {
            "Format": 20,
            "scale": scale,
            "Paint": paint,
        }

    def PaintVarScaleUniform(self, scale, paint):
        base = len(self.deltaset)
        return {
            "Format": 21,
            "scale": self.prepare_variable(scale, units="f2dot14"),
            "Paint": paint,
            "VarIndexBase": base,
        }

    def PaintScaleUniformAroundCenter(self, scale, center, paint):
        if any_variable(scale, *center):
            return self.PaintVarScaleUniformAroundCenter(scale, center, paint)
        return {
            "Format": 22,
            "scale": scale,
            "centerX": center[0],
            "centerY": center[1],
            "Paint": paint,
        }

    def PaintVarScaleUniformAroundCenter(self, scale, center, paint):
        base = len(self.deltaset)
        return {
            "Format": 23,
            "scale": self.prepare_variable(scale, units="f2dot14"),
            "centerX": self.prepare_variable(center[0]),
            "centerY": self.prepare_variable(center[1]),
            "Paint": paint,
            "VarIndexBase": base,
        }

    def PaintRotate(self, *args, angle=None, paint=None, center=None):
        if paint is None and len(args) == 1:
            paint = args[0]
        elif paint is None and angle is None and len(args) == 2:
            angle, paint = args
        elif paint is None and angle is None and center is None and len(args) == 3:
            angle, center, paint = args
        if paint is None or angle is None:
            raise ValueError("Couldn't understand arguments to PaintRotate")

        if center is not None:
            return self.PaintRotateAroundCenter(angle, center, paint)
        if any_variable(angle):
            return self.PaintVarRotate(angle, paint)
        return {"Format": 24, "angle": angle, "Paint": paint}

    def PaintVarRotate(self, angle, paint):
        base = len(self.deltaset)
        return {
            "Format": 25,
            "angle": self.prepare_variable(angle, units="angle"),
            "Paint": paint,
            "VarIndexBase": base,
        }

    def PaintRotateAroundCenter(self, angle, center, paint):
        if any_variable(angle, *center):
            return self.PaintVarRotateAroundCenter(angle, center, paint)
        return {
            "Format": 26,
            "angle": angle,
            "centerX": center[0],
            "centerY": center[1],
            "Paint": paint,
        }

    def PaintVarRotateAroundCenter(self, angle, center, paint):
        base = len(self.deltaset)
        return {
            "Format": 27,
            "angle": self.prepare_variable(angle, units="angle"),
            "centerX": self.prepare_variable(center[0]),
            "centerY": self.prepare_variable(center[1]),
            "Paint": paint,
            "VarIndexBase": base,
        }

    def PaintSkew(self, xSkewAngle, ySkewAngle, paint, center=None):
        if center is not None:
            return self.PaintSkewAroundCenter(xSkewAngle, ySkewAngle, center, paint)
        if any_variable(xSkewAngle, ySkewAngle):
            return self.PaintVarSkew(xSkewAngle, ySkewAngle, paint)

        return {
            "Format": 28,
            "xSkewAngle": xSkewAngle,
            "ySkewAngle": ySkewAngle,
            "Paint": paint,
        }

    def PaintVarSkew(self, xSkewAngle, ySkewAngle, paint):
        base = len(self.deltaset)
        return {
            "Format": 29,
            "xSkewAngle": self.prepare_variable(xSkewAngle, units="angle"),
            "ySkewAngle": self.prepare_variable(ySkewAngle, units="angle"),
            "Paint": paint,
            "VarIndexBase": base,
        }

    def PaintSkewAroundCenter(self, angle_x, angle_y, center, paint):
        if any_variable(angle_x, angle_y, *center):
            return self.PaintVarSkewAroundCenter(angle_x, angle_y, center, paint)
        return {
            "Format": 30,
            "xSkewAngle": angle_x,
            "ySkewAngle": angle_y,
            "centerX": center[0],
            "centerY": center[1],
            "Paint": paint,
        }

    def PaintVarSkewAroundCenter(self, angle_x, angle_y, center, paint):
        base = len(self.deltaset)
        return {
            "Format": 31,
            "xSkewAngle": self.prepare_variable(
                angle_x,
                units="angle",
            ),
            "ySkewAngle": self.prepare_variable(
                angle_y,
                units="angle",
            ),
            "centerX": self.prepare_variable(center[0]),
            "centerY": self.prepare_variable(center[1]),
            "Paint": paint,
            "VarIndexBase": base,
        }

    def PaintComposite(self, mode, src, dst):
        if mode.upper() not in CompositeMode._member_names_:
            raise ValueError(f"Unknown composite mode {mode}, must be one of: {CompositeMode._member_names_}")
        return {
            "Format": 32,
            "CompositeMode": mode,
            "SourcePaint": src,
            "BackdropPaint": dst,
        }

    def build_palette(self):
        palette = [compile_colors(stop) for stop in self.palette]
        t_palette = list(map(list, zip(*palette)))
        self.font["CPAL"] = buildCPAL(t_palette)

    def build_colr(self, glyphs):
        store = self.varstorebuilder.finish()
        mapping = store.optimize()
        self.deltaset = [mapping[v] for v in self.deltaset]
        self.font["COLR"] = buildCOLR(
            glyphs,
            varStore=store,
            varIndexMap=buildDeltaSetIndexMap(self.deltaset),
            version=1,
        )


def compile_paints(font, python_code):
    builder = PythonBuilder(font)
    methods = [x for x in dir(builder) if x.startswith("Paint")]
    this_locals = {"glyphs": {}, "font": font, "ColorLine": ColorLine}
    for method in methods:
        this_locals[method] = getattr(builder, method)
    exec(python_code, this_locals, this_locals)

    builder.build_colr(this_locals["glyphs"])
    builder.build_palette()


def main(args=None):
    import argparse
    from fontTools.ttLib import newTable
    import sys

    parser = argparse.ArgumentParser(
        description="Add paints to a font from a Python description"
    )
    parser.add_argument(
        "--drop-fvar",
        action="store_true",
        help="Drop an existing fvar table",
    )
    parser.add_argument(
        "--add-axis",
        action="append",
        help="Add an fvar axis. Axes are specified as 'tag:min:default:max:name'. May be used multiple times.",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="TTF",
        help="The file to write on (defaults to input file)",
    )
    parser.add_argument(
        "-p",
        "--paints",
        metavar="PY",
        default="paints.py",
        help="The paint description file (defaults to paints.py)",
    )
    parser.add_argument("font", metavar="TTF", help="The input font file")

    def add_axes(font: TTFont, axes: list[str]):
        if "fvar" in font:
            fvar = font["fvar"]
        else:
            font["fvar"] = fvar = newTable("fvar")
        nameTable = font["name"]

        for axis_def in axes:
            axis = Axis()
            (tag, minvalue, default, maxvalue, name) = axis_def.split(":")
            axis.axisTag = tag
            axis.defaultValue = float(default)
            axis.maxValue = float(maxvalue)
            axis.minValue = float(minvalue)
            name = dict(en=name)
            axis.axisNameID = nameTable.addMultilingualName(name, ttFont=font)
            fvar.axes.append(axis)

    args = parser.parse_args()

    if not args.output:
        args.output = args.font

    try:
        font = TTFont(args.font)
    except Exception as e:
        print(f"Could not read font {args.font}: {e}")
        sys.exit(1)

    if args.add_axis:
        if "gvar" in font:
            v = font["gvar"]  # Force decompilation
        add_axes(font, args.add_axis)
    try:
        paints = open(args.paints).read()
    except Exception as e:
        print(f"Could not read paints file {args.paints}: {e}")
        sys.exit(1)

    print("Adding paints...")
    compile_paints(font, paints)

    try:
        print("Saving...")
        font.save(args.output)
        print(args.output)
    except Exception as e:
        print(f"Could not save on {args.output} paints: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
