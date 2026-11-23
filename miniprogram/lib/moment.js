const api = require("./api");

const emptyDraft = { momentRatio: "portrait", momentAsset: null, momentNote: "", momentKey: "", momentJob: "" };
const newKey = () => "moment-" + Date.now() + "-" + Math.random().toString(36).slice(2);

module.exports = {
  data: { ...emptyDraft, momentPhoto: "", momentCost: null, momentError: "" },
  methods: {
    async loadMoment() {
      try {
        const price = await api.request("moments/price");
        if (this.momentWorkspace !== price.workspace) {
          this.momentWorkspace = price.workspace;
          const saved = wx.getStorageSync("trupic.moment." + price.workspace);
          this.setData({ ...emptyDraft, ...saved, momentPhoto: "", momentError: "" });
        }
        this.setData({ momentCost: price.cost, momentError: "" });
        const asset = this.data.momentAsset;
        if (asset && !this.data.momentPhoto) {
          const photo = await api.download(asset.original);
          if (this.data.momentAsset?.id === asset.id) this.setData({ momentPhoto: photo });
        }
      } catch (e) {
        this.setData({ momentError: e.message });
      }
    },
    rememberMoment(fields) {
      this.setData(fields);
      const { momentRatio, momentAsset, momentNote, momentKey, momentJob } = this.data;
      wx.setStorageSync("trupic.moment." + this.momentWorkspace, { momentRatio, momentAsset, momentNote, momentKey, momentJob });
    },
    momentFormat(e) {
      const ratio = e.currentTarget.dataset.ratio;
      if (this.data.busy || this.data.momentRatio === ratio) return;
      this.rememberMoment({ momentRatio: ratio, momentKey: "", momentJob: "", momentError: "" });
    },
    momentInput(e) {
      this.rememberMoment({ momentNote: e.detail.value, momentKey: "", momentJob: "", momentError: "" });
    },
    takeMomentPhoto() {
      if (this.data.busy || !this.momentWorkspace) return;
      this.setData({ busy: true, momentError: "" });
      wx.chooseMedia({
        count: 1, mediaType: ["image"], sourceType: ["camera", "album"], sizeType: ["compressed"],
        success: async ({ tempFiles }) => {
          try {
            const file = tempFiles[0].tempFilePath;
            const asset = await api.upload(file);
            if (asset.risk) throw new Error("这张照片看不清，换一张或靠近一点再拍。");
            this.rememberMoment({ momentAsset: asset, momentPhoto: file, momentKey: "", momentJob: "",
              momentNote: this.data.momentJob ? "" : this.data.momentNote });
          } catch (e) {
            this.setData({ momentError: e.message });
          } finally {
            this.setData({ busy: false });
          }
        },
        fail: (e) => this.setData({ busy: false, momentError: /cancel/i.test(e.errMsg) ? "" : "无法打开相机或相册，请检查微信权限后重试。" }),
      });
    },
    async makeMoment() {
      if (this.data.busy || !this.data.momentAsset || this.data.momentCost === null) return;
      this.setData({ busy: true, momentError: "" });
      try {
        if (!this.data.momentJob) {
          if (!this.data.momentKey) this.rememberMoment({ momentKey: newKey() });
          const job = await api.request("moments", "POST", {
            asset: this.data.momentAsset.id, ratio: this.data.momentRatio, note: this.data.momentNote.trim(),
            confirmed: true, confirmedCost: this.data.momentCost, requestKey: this.data.momentKey,
          });
          this.rememberMoment({ momentJob: job.id });
        }
        wx.navigateTo({ url: "/pages/result/result?job=" + this.data.momentJob });
      } catch (e) {
        this.setData({ momentError: e.message });
        await this.loadMoment();
        this.setData({ momentError: e.message });
      } finally {
        this.setData({ busy: false });
      }
    },
  },
};
