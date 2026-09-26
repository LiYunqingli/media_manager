-- =============================================================================
--  MediaManager —— 增量数据库变更脚本
--  数据库名: media_manager
--
--  【使用规则 / 必读】
--  1) media_manager.sql 是「基线全量脚本」，只负责从零构建数据库，禁止再改它。
--  2) 此后每一次结构或基础数据的变更，都按时间顺序追加到本文件底部。
--     每条变更必须：可重复执行（幂等）或明确标注不可重复；必须写注释说明原因与日期。
--  3) 当本文件被使用到第 3 次变更时：
--        a) 把本文件内容整体合并进 media_manager.sql 的对应位置，
--           并调整 media_manager.sql 使其重新成为一个「可从零构建」的基线；
--        b) 清空本文件，变更计数归零，重新开始。
--     这样保证新人始终只需跑一个全量脚本即可得到最新结构。
--
--  【当前变更计数】 1 / 3
-- =============================================================================

USE `media_manager`;

-- -----------------------------------------------------------------------------
-- [变更 #1] 新增 m3u8 链接下载导入任务表
-- 日期: 2026-09-26
-- 原因: 管理端新增「m3u8 链接下载导入」入口（底层为 N_m3u8DL-RE），需要一张表
--       承载任务队列、下载进度与入库结果，供管理端页面与浏览器插件（X-API-Token）
--       共同使用。字段语义与 upload_session 对齐，便于前端复用同一套进度展示。
-- 说明: CREATE TABLE IF NOT EXISTS，可重复执行。
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `download_task` (
  `task_id`      VARCHAR(40)   NOT NULL COMMENT '任务ID（uuid hex）',
  `user_id`      INT UNSIGNED  NOT NULL COMMENT '任务归属用户',
  `source`       VARCHAR(24)   NOT NULL DEFAULT 'admin'
                 COMMENT '来源: admin=管理端页面 / api=插件或脚本（X-API-Token）',
  `url`          TEXT          NOT NULL COMMENT 'm3u8/mpd 链接',
  `headers`      TEXT          NULL     COMMENT '额外请求头 JSON（Cookie/Referer/UA）',
  `title`        VARCHAR(255)  NOT NULL DEFAULT '' COMMENT '视频名称',
  `cover_url`    VARCHAR(1024) NOT NULL DEFAULT '' COMMENT '远程封面地址',
  `category_id`  INT UNSIGNED  NOT NULL DEFAULT 0 COMMENT '目标分类',
  `description`  TEXT          NULL     COMMENT '视频简介',
  `sort`         INT           NOT NULL DEFAULT 0 COMMENT '排序值',
  `stage`        VARCHAR(24)   NOT NULL DEFAULT 'queued'
                 COMMENT '阶段: queued/downloading/muxing/ingesting/probing/covering/finished/failed/cancelled',
  `percent`      FLOAT         NOT NULL DEFAULT 0 COMMENT '整体百分比 0-100',
  `total_bytes`  BIGINT        NOT NULL DEFAULT 0 COMMENT '预计/已下载总字节',
  `done_bytes`   BIGINT        NOT NULL DEFAULT 0 COMMENT '已下载字节',
  `speed`        BIGINT        NOT NULL DEFAULT 0 COMMENT '瞬时速度 字节/秒',
  `eta`          INT           NOT NULL DEFAULT 0 COMMENT '预计剩余秒数',
  `staging_dir`  VARCHAR(500)  NOT NULL DEFAULT '' COMMENT '下载暂存目录（相对 storage）',
  `file_path`    VARCHAR(500)  NOT NULL DEFAULT '' COMMENT '视频落盘路径（相对 storage）',
  `cover`        VARCHAR(500)  NOT NULL DEFAULT '' COMMENT '封面落盘路径（相对 storage）',
  `video_id`     INT UNSIGNED  NOT NULL DEFAULT 0 COMMENT '入库产生的视频ID',
  `message`      VARCHAR(500)  NOT NULL DEFAULT '' COMMENT '阶段提示',
  `error`        VARCHAR(500)  NOT NULL DEFAULT '' COMMENT '错误信息',
  `log_tail`     TEXT          NULL     COMMENT 'N_m3u8DL-RE 输出尾部（排障用）',
  `elapsed`      FLOAT         NOT NULL DEFAULT 0 COMMENT '耗时（秒）',
  `created_at`   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `started_at`   DATETIME      NULL,
  `finished_at`  DATETIME      NULL,
  `updated_at`   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`task_id`),
  KEY `idx_stage` (`stage`),
  KEY `idx_user` (`user_id`),
  KEY `idx_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='m3u8 链接下载导入任务';

-- -----------------------------------------------------------------------------
-- [变更 #2] 模板示例（请勿删除注释头，按此格式追加）
-- 日期: YYYY-MM-DD
-- 原因: xxx
-- -----------------------------------------------------------------------------
-- ALTER TABLE `video` ADD COLUMN `example_col` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '示例' AFTER `status`;
