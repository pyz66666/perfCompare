# 内核 commitId 通过 gitee tag 查询获得，而非要求测试流程额外记录

报告需要两侧的内核版本与 commitId，但结果目录里既没有内核版本，也没有版本到 commit 的对应关系。决定：内核版本由使用者提供，工具用 `git ls-remote --tags https://gitee.com/openeuler/kernel.git <版本号>` 把版本-发布号直接换成 commit 哈希，结果落本地缓存供离线复用。理由是 openEuler 内核仓库的 tag 名就是 RPM 的版本-发布号（实测 `6.6.0-72.3.0` 直接命中，单次查询约 0.8 秒，无需 clone），且相比「要求内网测试流程多落一份内核信息」，此法不改动既有流程。

## Consequences

- 依赖 gitee 可达；离线时只能用本地缓存。
- 版本号必须归一化：去掉 `uname -r` 的架构后缀，并依次尝试带与不带 `.oe2403` 后缀两种形式（仓库中两种命名都存在）。
