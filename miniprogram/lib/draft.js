// Leave an existing brief intact until the merchant accepts a replacement.
function confirmBriefChange(current, next, apply) {
  if (!current || !current.trim() || current === next) {
    apply();
    return;
  }
  wx.showModal({
    title: "替换当前需求？",
    content: "已填写的需求将替换为所选内容，商品素材会保留。",
    cancelText: "保留原文",
    confirmText: "替换需求",
    confirmColor: "#184b32",
    success: ({ confirm }) => { if (confirm) apply(); },
  });
}
module.exports = { confirmBriefChange };
