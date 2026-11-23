const config = require("../config");
function base() {
  const production = config.production.replace(/\/$/, "");
  if (production && !/^https:\/\//.test(production))
    throw new Error("业务域名需要使用 HTTPS");
  if (production) return production;
  if (wx.getAccountInfoSync().miniProgram.envVersion === "develop")
    return config.development;
  throw new Error("请先配置小程序的 HTTPS 业务域名");
}

const cookieKey = () => "trupic.session:" + base();
function header() {
  const cookie = wx.getStorageSync(cookieKey());
  return cookie ? { Cookie: cookie, "X-Trupic-Native": "1" } : { "X-Trupic-Native": "1" };
}
function persist(response) {
  const headers = response.header || {};
  const field = Object.keys(headers).find(
    (k) => k.toLowerCase() === "set-cookie",
  );
  const value = []
    .concat(response.cookies || [], field ? headers[field] : [])
    .join(", ");
  const match = value.match(/(?:^|,\s*)(trupic_workspace=([^;,\s]*))/);
  if (match) wx.setStorageSync(cookieKey(), match[2] ? match[1] : "");
}
function network(method, options) {
  return new Promise((resolve, reject) =>
    wx[method]({
      ...options,
      header: header(),
      timeout: 120000,
      success(response) {
        persist(response);
        if (response.statusCode >= 200 && response.statusCode < 300)
          return resolve(response);
        let data = response.data;
        try {
          if (typeof data === "string") data = JSON.parse(data);
        } catch (_) {}
        reject(
          new Error((data && data.error) || "服务暂时无法完成此操作，请重试"),
        );
      },
      fail: () => reject(new Error("无法连接创作服务，请检查网络和业务域名")),
    }),
  );
}
// Requests and private downloads must share the same signed Flask workspace.
let starting;
async function ready() {
  if (wx.getStorageSync(cookieKey())) return;
  if (!starting)
    starting = network("request", { url: base() + "/api/state" })
      .then(() => {
        if (!wx.getStorageSync(cookieKey()))
          throw new Error("工作空间会话未建立，请重试");
      })
      .finally(() => {
        starting = null;
      });
  await starting;
}
async function request(path, method = "GET", data) {
  await ready();
  return (
    await network("request", { url: base() + "/api/" + path, method, data })
  ).data;
}
async function upload(path) {
  await ready();
  const res = await network("uploadFile", {
    url: base() + "/api/assets",
    filePath: path,
    name: "image",
  });
  return JSON.parse(res.data);
}
async function download(path) {
  if (!path.startsWith("/api/")) throw new Error("文件地址无效");
  await ready();
  return (await network("downloadFile", { url: base() + path })).tempFilePath;
}
function message(e) {
  wx.showModal({
    title: "响指出片",
    content: e.message || "请重试",
    showCancel: false,
  });
}
module.exports = { request, upload, download, message };
