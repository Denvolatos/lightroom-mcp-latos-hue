"""调整参数的中文名称。找不到的参数显示原名。"""
from __future__ import annotations

_COLORS = {"Red": "红色", "Orange": "橙色", "Yellow": "黄色", "Green": "绿色",
           "Aqua": "浅绿色", "Blue": "蓝色", "Purple": "紫色", "Magenta": "洋红色"}

PARAM_NAMES: dict[str, str] = {
    "Exposure2012": "曝光", "Contrast2012": "对比度", "Highlights2012": "高光", "Shadows2012": "阴影",
    "Whites2012": "白色色阶", "Blacks2012": "黑色色阶", "Texture": "纹理", "Clarity2012": "清晰度",
    "Dehaze": "去朦胧", "Vibrance": "自然饱和度", "Saturation": "饱和度",
    "Temperature": "色温", "Tint": "色调",
    "SplitToningShadowHue": "阴影色相", "SplitToningShadowSaturation": "阴影饱和度", "ColorGradeShadowLum": "阴影明度",
    "SplitToningHighlightHue": "高光色相", "SplitToningHighlightSaturation": "高光饱和度", "ColorGradeHighlightLum": "高光明度",
    "ColorGradeMidtoneHue": "中间调色相", "ColorGradeMidtoneSat": "中间调饱和度", "ColorGradeMidtoneLum": "中间调明度",
    "ColorGradeGlobalHue": "全局色相", "ColorGradeGlobalSat": "全局饱和度", "ColorGradeGlobalLum": "全局明度",
    "SplitToningBalance": "颜色分级平衡", "ColorGradeBlending": "颜色分级混合",
    "ShadowTint": "校准阴影色调", "RedHue": "校准红原色色相", "RedSaturation": "校准红原色饱和度",
    "GreenHue": "校准绿原色色相", "GreenSaturation": "校准绿原色饱和度",
    "BlueHue": "校准蓝原色色相", "BlueSaturation": "校准蓝原色饱和度",
    "ParametricShadows": "曲线阴影", "ParametricDarks": "曲线暗色调",
    "ParametricLights": "曲线亮色调", "ParametricHighlights": "曲线高光",
    "Sharpness": "锐化数量", "SharpenRadius": "锐化半径", "SharpenDetail": "锐化细节", "SharpenEdgeMasking": "锐化蒙版",
    "LuminanceSmoothing": "明亮度降噪", "LuminanceNoiseReductionDetail": "明亮度降噪细节",
    "LuminanceNoiseReductionContrast": "明亮度降噪对比度", "ColorNoiseReduction": "颜色降噪",
    "ColorNoiseReductionDetail": "颜色降噪细节", "ColorNoiseReductionSmoothness": "颜色降噪平滑度",
    "PostCropVignetteAmount": "裁剪后暗角数量", "PostCropVignetteMidpoint": "裁剪后暗角中点",
    "PostCropVignetteFeather": "裁剪后暗角羽化", "PostCropVignetteRoundness": "裁剪后暗角圆度",
    "PostCropVignetteHighlightContrast": "裁剪后暗角高光",
    "GrainAmount": "颗粒数量", "GrainSize": "颗粒大小", "GrainFrequency": "颗粒粗糙度",
    "VignetteAmount": "镜头暗角数量", "VignetteMidpoint": "镜头暗角中点",
    "DefringePurpleAmount": "去紫边", "DefringeGreenAmount": "去绿边",
    "CropLeft": "裁剪左边", "CropTop": "裁剪上边", "CropRight": "裁剪右边", "CropBottom": "裁剪下边", "CropAngle": "拉直角度",
    "ToneCurvePV2012": "亮度曲线", "ToneCurvePV2012Red": "红通道曲线",
    "ToneCurvePV2012Green": "绿通道曲线", "ToneCurvePV2012Blue": "蓝通道曲线",
}
for _en, _zh in _COLORS.items():
    PARAM_NAMES["HueAdjustment" + _en] = _zh + "色相"
    PARAM_NAMES["SaturationAdjustment" + _en] = _zh + "饱和度"
    PARAM_NAMES["LuminanceAdjustment" + _en] = _zh + "明亮度"


def param_name(key: str) -> str:
    return PARAM_NAMES.get(key, key)
