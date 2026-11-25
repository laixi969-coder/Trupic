// Album access is the merchant's choice. Ask once, then report the true result.
function call(method, options) {
  return new Promise((resolve, reject) =>
    wx[method]({ ...options, success: resolve, fail: reject }),
  );
}

function authSetting(open) {
  return call(open ? "openSetting" : "getSetting", {}).catch(() => ({
    authSetting: {},
  }));
}

// Resolves after the file is in the album, or hands it over for a long-press save.
async function saveToAlbum(path, video) {
  const scope = "scope.writePhotosAlbum";
  const method = video ? "saveVideoToPhotosAlbum" : "saveImageToPhotosAlbum";
  try {
    await call(method, { filePath: path });
    return "已保存到相册";
  } catch (failure) {
    if ((await authSetting()).authSetting[scope] !== false) {
      // Not a permission the merchant can grant here: still let the file be kept.
      if (wx.previewMedia && video) wx.previewMedia({ sources: [{ url: path, type: "video" }] });
      else if (wx.previewImage) wx.previewImage({ current: path, urls: [path] });
      return video ? "未能自动保存，长按视频可保存" : "未能自动保存，长按图片可保存";
    }
    const choice = await call("showModal", {
      title: "允许保存到相册",
      content: "在设置中打开「保存到相册」，作品就会自动保存。",
      confirmText: "去设置",
      cancelText: "暂不",
    }).catch(() => ({ confirm: false }));
    if (!choice.confirm || (await authSetting(true)).authSetting[scope] !== true)
      throw new Error("未允许保存到相册，作品还没有保存。");
    await call(method, { filePath: path });
    return "已保存到相册";
  }
}

module.exports = { saveToAlbum };
