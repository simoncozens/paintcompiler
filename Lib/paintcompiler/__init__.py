import logging
from fontTools.ttLib import TTFont
from fontTools.colorLib.builder import buildCOLR, buildCPAL
from fontTools.ttLib.tables.otTables import CompositeMode
from fontTools.varLib.varStore import OnlineVarStoreBuilder
from fontTools.varLib.builder import buildDeltaSetIndexMap
from fontTools.feaLib.variableScalar import VariableScalar
from fontTools.varLib.instancer import _TupleVarStoreAdapter
from fontTools.misc.fixedTools import floatToFixed, fixedToFloat
from fontTools.ttLib.tables._f_v_a_r import Axis
from typing import List
import re


def compile_color(c):
    try:
        assert c[0] == "#"
        return tuple(int(x, 16) / 255 for x in [c[1:3], c[3:5], c[5:7], c[7:9]])
    except:
        raise ValueError(
            f"Could not understand color {c}; should be hex digits in form #RRGGBBAA"
        )


def compile_palette_entry(colors):
    return [compile_color(c) for c in colors]


def compile_palettes(entries):
    # each element of the array should be the same length;
    # if it is one, pad to the max length, if not raise an error
    max_length = max(len(entry) for entry in entries)
    for index, entry in enumerate(entries):
        if len(entry) == 1:
            entries[index] = entry * max_length
        elif len(entry) != max_length:
            raise ValueError(
                f"Pallete index {index} specifies {len(entry)} palettes ({entry}), but should have {max_length}"
            )
    return [compile_palette_entry(colors) for colors in entries]


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
            if isinstance(v, (list, tuple)) and isinstance(v[1], (float, int, dict)):
                alpha = v[1]
                v = v[0]
            if isinstance(alpha, (dict, str)):
                self.needs_variable = True
            if isinstance(k, (dict, str)):
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
            skeleton = compiler.prepare_variables(
                [
                    {"name": "StopOffset", "value": k, "units": "f2dot14"},
                    {"name": "Alpha", "value": alpha, "units": "f2dot14"},
                ]
            )
            obj["ColorStop"].append(
                skeleton
                | {
                    "PaletteIndex": compiler.get_palette_index(v),
                }
            )
        return obj


def is_variable(thing):
    if isinstance(thing, ColorLine):
        return thing.needs_variable
    return isinstance(thing, (str, dict))


def any_variable(*things):
    return any(is_variable(x) for x in things)


def _convert_default_from_variable(default, units=None):
    if units == "f2dot14":
        return fixedToFloat(default, 14)
    elif units == "angle":
        return fixedToFloat(default, 14) * 180
    elif units == "fixed":
        return fixedToFloat(default, 16)
    elif units is not None:
        raise ValueError(f"Unknown units {units}")
    return default


class PythonBuilder:
    def __init__(self, font: TTFont) -> None:
        self.font = font
        self.explicit_palette = False
        self.palette = []
        self.palette_flags = {}
        self.variations = []
        self.varindexbases = []
        self.deltaset: list[int] = []
        self.axes = []
        self.varstorebuilder = None
        if "fvar" in font:
            self.axes = font["fvar"].axes
            axis_tags = [x.axisTag for x in self.axes]
            self.varstorebuilder = OnlineVarStoreBuilder(axis_tags)

    def make_var_scalar(self, s, units=None):
        if not self.varstorebuilder:
            raise ValueError(
                "Attempt to use a variable scalar %s, but this was not a variable font"
                % s
            )
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
                try:
                    locations, value = values.split(":")
                except ValueError:
                    raise ValueError(
                        f"Could not understand variable parameter {s}, "
                        "should be of the form tag=value,tag=value:default"
                    )
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
            if units != "fixed" and (
                converter(value) <= -32768 or converter(value) >= 32768
            ):
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
        if isinstance(color, int):
            # Check if palette exists and is long enough
            if color >= len(self.palette):
                raise ValueError(
                    f"Palette index {color} out of range; call SetColors first"
                )
            return color
        if self.explicit_palette:
            raise ValueError(
                f"Color {color} specified, but SetColors was called; "
                "use palette index directly instead"
            )
        if not isinstance(color, list):
            color = [color]
        if color not in self.palette:
            self.palette.append(color)
        return self.palette.index(color)

    def prepare_variables(self, variables):
        # Have I seen this precise set of variables before? If so, return a copy
        for these_variables, skeleton in self.varindexbases:
            if these_variables == variables:
                return dict(skeleton)

        base = len(self.deltaset)
        skeleton = {"VarIndexBase": len(self.deltaset)}
        for variable in variables:
            name = variable["name"]
            value = variable["value"]
            units = variable.get("units")
            vs = self.make_var_scalar(value, units=units)
            default, index = vs.add_to_variation_store(self.varstorebuilder)
            default = _convert_default_from_variable(default, units)
            self.deltaset.append(index)
            skeleton[name] = default

        self.varindexbases.append((variables, skeleton))
        return skeleton

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
        skeleton = self.prepare_variables(
            [{"name": "Alpha", "value": alpha, "units": "f2dot14"}]
        )
        return {
            **skeleton,
            "Format": 3,
            "PaletteIndex": self.get_palette_index(col_or_colrs),
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
        skeleton = self.prepare_variables(
            [
                {"name": "x0", "value": pt0[0]},
                {"name": "y0", "value": pt0[1]},
                {"name": "x1", "value": pt1[0]},
                {"name": "y1", "value": pt1[1]},
                {"name": "x2", "value": pt2[0]},
                {"name": "y2", "value": pt2[1]},
            ]
        )
        return {
            **skeleton,
            "Format": 5,
            "ColorLine": colorline.compile_var(self),
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
        skeleton = self.prepare_variables(
            [
                {"name": "x0", "value": pt0[0]},
                {"name": "y0", "value": pt0[1]},
                {"name": "r0", "value": rad0},
                {"name": "x1", "value": pt1[0]},
                {"name": "y1", "value": pt1[1]},
                {"name": "r1", "value": rad1},
            ]
        )
        return {
            **skeleton,
            "Format": 7,
            "ColorLine": varcolorline.compile_var(self),
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
        skeleton = self.prepare_variables(
            [
                {"name": "centerX", "value": pt[0]},
                {"name": "centerY", "value": pt[1]},
                {"name": "startAngle", "value": startAngle, "units": "angle"},
                {"name": "endAngle", "value": endAngle, "units": "angle"},
            ]
        )
        return {
            **skeleton,
            "Format": 9,
            "ColorLine": varcolorline.compile_var(self),
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
        skeleton = self.prepare_variables(
            [
                {"name": "xx", "value": matrix[0], "units": "fixed"},
                {"name": "xy", "value": matrix[1], "units": "fixed"},
                {"name": "yx", "value": matrix[2], "units": "fixed"},
                {"name": "yy", "value": matrix[3], "units": "fixed"},
                {"name": "dx", "value": matrix[4], "units": "fixed"},
                {"name": "dy", "value": matrix[5], "units": "fixed"},
            ]
        )
        return {
            "Format": 13,
            "Paint": paint,
            "Transform": skeleton,
        }

    def PaintTranslate(self, dx, dy, paint):
        if any_variable(dx, dy):
            return self.PaintVarTranslate(dx, dy, paint)
        return {"Format": 14, "dx": dx, "dy": dy, "Paint": paint}

    def PaintVarTranslate(self, dx, dy, paint):
        skeleton = self.prepare_variables(
            [
                {"name": "dx", "value": dx},
                {"name": "dy", "value": dy},
            ]
        )
        return {
            **skeleton,
            "Format": 15,
            "Paint": paint,
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
        skeleton = self.prepare_variables(
            [
                {"name": "scaleX", "value": scale_x, "units": "f2dot14"},
                {"name": "scaleY", "value": scale_y, "units": "f2dot14"},
            ]
        )
        return {
            **skeleton,
            "Format": 17,
            "Paint": paint,
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
        skeleton = self.prepare_variables(
            [
                {"name": "scaleX", "value": scale_x, "units": "f2dot14"},
                {"name": "scaleY", "value": scale_y, "units": "f2dot14"},
                {"name": "centerX", "value": center[0]},
                {"name": "centerY", "value": center[1]},
            ]
        )
        return {
            **skeleton,
            "Format": 19,
            "Paint": paint,
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
        skeleton = self.prepare_variables(
            [{"name": "scale", "value": scale, "units": "f2dot14"}]
        )
        return {
            **skeleton,
            "Format": 21,
            "Paint": paint,
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
        skeleton = self.prepare_variables(
            [
                {"name": "scale", "value": scale, "units": "f2dot14"},
                {"name": "centerX", "value": center[0]},
                {"name": "centerY", "value": center[1]},
            ]
        )
        return {
            **skeleton,
            "Format": 23,
            "Paint": paint,
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
        skeleton = self.prepare_variables(
            [{"name": "angle", "value": angle, "units": "angle"}]
        )

        return {
            **skeleton,
            "Format": 25,
            "Paint": paint,
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
        skeleton = self.prepare_variables(
            [
                {"name": "angle", "value": angle, "units": "angle"},
                {"name": "centerX", "value": center[0]},
                {"name": "centerY", "value": center[1]},
            ]
        )
        return {
            **skeleton,
            "Format": 27,
            "Paint": paint,
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
        skeleton = self.prepare_variables(
            [
                {"name": "xSkewAngle", "value": xSkewAngle, "units": "angle"},
                {"name": "ySkewAngle", "value": ySkewAngle, "units": "angle"},
            ]
        )
        return {
            **skeleton,
            "Format": 29,
            "Paint": paint,
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

    def PaintVarSkewAroundCenter(self, xSkewAngle, ySkewAngle, center, paint):
        skeleton = self.prepare_variables(
            [
                {"name": "xSkewAngle", "value": xSkewAngle, "units": "angle"},
                {"name": "ySkewAngle", "value": ySkewAngle, "units": "angle"},
                {"name": "centerX", "value": center[0]},
                {"name": "centerY", "value": center[1]},
            ]
        )
        return {
            **skeleton,
            "Format": 31,
            "Paint": paint,
        }

    def PaintComposite(self, mode, src, dst):
        if mode.upper() not in CompositeMode._member_names_:
            raise ValueError(
                f"Unknown composite mode {mode}, must be one of: {CompositeMode._member_names_}"
            )
        return {
            "Format": 32,
            "CompositeMode": mode,
            "SourcePaint": src,
            "BackdropPaint": dst,
        }

    def SetColors(self, colors):
        self.explicit_palette = True
        # colors should be an array of strings or array of arrays
        for index, color in enumerate(colors):
            if not isinstance(color, list):
                color = colors[index] = [color]
            for c in color:
                if not re.match(r"^#[0-9a-fA-F]{8}$", c):
                    raise ValueError(
                        f"Color {c} at index {index} is not a valid color; "
                        "should be in the form #RRGGBBAA"
                    )

        self.palette = colors

    def SetPaletteFlags(self, palette_index, flags):
        if not self.palette:
            raise ValueError("Use colors or SetPalette before SetPaletteFlags")
        num_palettes = max(len(colors) for colors in self.palette)
        if palette_index >= num_palettes:
            raise ValueError(
                f"Palette index {palette_index} out of range; "
                f"should be less than {num_palettes}"
            )
        if flags not in ["light", "dark"]:
            raise ValueError(f"Unknown palette flags {flags}")
        if palette_index not in self.palette_flags:
            self.palette_flags[palette_index] = 0
        if flags == "light":
            self.palette_flags[palette_index] |= 0x0001
        else:
            self.palette_flags[palette_index] |= 0x0002

    def SetDarkMode(self, palette_index):
        self.SetPaletteFlags(palette_index, "dark")

    def SetLightMode(self, palette_index):
        self.SetPaletteFlags(palette_index, "light")

    def build_palette(self):
        palette = compile_palettes(self.palette)
        t_palette = list(map(list, zip(*palette)))
        if t_palette:
            self.font["CPAL"] = buildCPAL(t_palette)
        if self.palette_flags:
            self.font["CPAL"].version = 1
            self.font["CPAL"].paletteTypes = [
                self.palette_flags.get(i, 0) for i in range(len(t_palette))
            ]

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
    methods = [x for x in dir(builder) if x.startswith("Paint")] + [
        "SetColors",
        "SetPaletteFlags",
        "SetDarkMode",
        "SetLightMode",
    ]
    this_locals = {"glyphs": {}, "font": font, "ColorLine": ColorLine}
    for method in methods:
        this_locals[method] = getattr(builder, method)
    exec(python_code, this_locals, this_locals)

    builder.build_colr(this_locals["glyphs"])
    builder.build_palette()


def update_varstore(font, tag, orig_axes):
    if tag not in font or not font[tag].table.VarStore:
        return
    store = font[tag].table.VarStore
    tupleVarStore = _TupleVarStoreAdapter.fromItemVarStore(store, orig_axes)
    tupleVarStore.axisOrder = [ax.axisTag for ax in font["fvar"].axes]
    font[tag].table.VarStore = tupleVarStore.asItemVarStore()


def add_axes(font: TTFont, axes: List[str]):
    if "fvar" in font:
        fvar = font["fvar"]
    else:
        font["fvar"] = fvar = newTable("fvar")
    font.ensureDecompiled(True)
    orig_axes = list(fvar.axes)
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
        for instance in fvar.instances:
            instance.coordinates[axis.axisTag] = axis.defaultValue
        if "avar" in font:
            font["avar"].segments[tag] = {}

    for tag in ["GDEF", "HVAR", "VVAR", "MVAR"]:
        update_varstore(font, tag, orig_axes)


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
