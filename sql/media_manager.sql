-- =============================================================================
--  MediaManager 视频管理系统 —— 全量数据库脚本
--  数据库名: media_manager
--  字符集  : utf8mb4 / utf8mb4_general_ci
--  引擎    : InnoDB
--
--  【重要约定】
--  1. 该文件只承载「可一次性初始化」的全量结构 + 基础数据。
--  2. 后续任何数据库变更，禁止直接改本文件，请统一写入同目录 update.sql。
--  3. 当 update.sql 累计到第 3 次变更（或按需提前合并）时，把它的内容整体合并进
--     本文件 —— 新增表按序号追加到末尾，字段/索引变更直接改对应表定义 —— 使本文件
--     重新成为一个「可从零构建」的基线，然后清空 update.sql、计数归零。
--     详见 doc/02-数据库设计.md。
--
--  【基线版本】 v1.1.0
--    v1.0.0  初始 10 张表 + 内置账号与示例分类
--    v1.1.0  合并 update.sql 变更 #1：新增表 11 `download_task`（m3u8 下载导入任务）
-- =============================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

CREATE DATABASE IF NOT EXISTS `media_manager`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_general_ci;

USE `media_manager`;

-- -----------------------------------------------------------------------------
-- 1. 用户表
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `sys_user`;
CREATE TABLE `sys_user` (
  `id`            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `username`      VARCHAR(64)  NOT NULL                COMMENT '登录账号，唯一',
  `password`      VARCHAR(255) NOT NULL                COMMENT '密码散列，格式 pbkdf2_sha256$rounds$salt$hash',
  `nickname`      VARCHAR(64)  NOT NULL DEFAULT ''     COMMENT '昵称',
  `avatar`        VARCHAR(512) NOT NULL DEFAULT ''     COMMENT '头像地址',
  `email`         VARCHAR(128) NOT NULL DEFAULT ''     COMMENT '邮箱',
  `phone`         VARCHAR(32)  NOT NULL DEFAULT ''     COMMENT '手机号',
  `role`          ENUM('admin','user') NOT NULL DEFAULT 'user' COMMENT '角色',
  `status`        TINYINT      NOT NULL DEFAULT 1      COMMENT '状态 1=正常 0=禁用',
  `remark`        VARCHAR(255) NOT NULL DEFAULT ''     COMMENT '备注',
  `last_login_at` DATETIME     DEFAULT NULL            COMMENT '最后登录时间',
  `last_login_ip` VARCHAR(64)  NOT NULL DEFAULT ''     COMMENT '最后登录IP',
  `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_username` (`username`),
  KEY `idx_role_status` (`role`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='用户表';

-- -----------------------------------------------------------------------------
-- 2. 视频分类表
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `category`;
CREATE TABLE `category` (
  `id`          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name`        VARCHAR(64)  NOT NULL                COMMENT '分类名称',
  `description` VARCHAR(255) NOT NULL DEFAULT ''     COMMENT '分类描述',
  `cover`       VARCHAR(512) NOT NULL DEFAULT ''     COMMENT '分类封面',
  `sort`        INT          NOT NULL DEFAULT 0      COMMENT '排序值，越小越靠前',
  `status`      TINYINT      NOT NULL DEFAULT 1      COMMENT '状态 1=启用 0=隐藏',
  `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_name` (`name`),
  KEY `idx_sort_status` (`sort`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='视频分类表';

-- -----------------------------------------------------------------------------
-- 3. 视频表
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `video`;
CREATE TABLE `video` (
  `id`            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `category_id`   INT UNSIGNED NOT NULL                COMMENT '所属分类',
  `title`         VARCHAR(255) NOT NULL                COMMENT '视频标题',
  `description`   TEXT                                 COMMENT '视频简介',
  `cover`         VARCHAR(512) NOT NULL DEFAULT ''     COMMENT '封面地址(相对 storage)',
  `path`          VARCHAR(512) NOT NULL                COMMENT '视频文件地址(相对 storage)',
  `original_name` VARCHAR(255) NOT NULL DEFAULT ''     COMMENT '上传时的原始文件名',
  `duration`      FLOAT        NOT NULL DEFAULT 0      COMMENT '时长(秒)',
  `size`          BIGINT       NOT NULL DEFAULT 0      COMMENT '文件大小(字节)',
  `width`         INT          NOT NULL DEFAULT 0      COMMENT '宽度',
  `height`        INT          NOT NULL DEFAULT 0      COMMENT '高度',
  `bitrate`       INT          NOT NULL DEFAULT 0      COMMENT '码率(bps)',
  `mime`          VARCHAR(64)  NOT NULL DEFAULT ''     COMMENT '媒体类型',
  `cover_source`  TINYINT      NOT NULL DEFAULT 0      COMMENT '封面来源 0=自动抽帧 1=手动上传',
  `view_count`    INT UNSIGNED NOT NULL DEFAULT 0      COMMENT '播放次数(有效观看>=10s 计一次)',
  `favorite_count` INT UNSIGNED NOT NULL DEFAULT 0     COMMENT '收藏数(冗余统计)',
  `sort`          INT          NOT NULL DEFAULT 0      COMMENT '排序值',
  `status`        TINYINT      NOT NULL DEFAULT 1      COMMENT '状态 1=上架 0=下架',
  `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_category_status` (`category_id`, `status`),
  KEY `idx_view_count` (`view_count`),
  KEY `idx_created_at` (`created_at`),
  FULLTEXT KEY `ft_title_desc` (`title`, `description`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='视频表';

-- -----------------------------------------------------------------------------
-- 4. 用户-分类 权限规则
--    allow=1 白名单：若某用户存在任意 allow=1 记录，则该用户【只能】看到这些分类
--    allow=0 黑名单：在可见范围内【禁止】这些分类
--    黑名单优先级高于白名单。
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `user_category_rule`;
CREATE TABLE `user_category_rule` (
  `id`          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`     INT UNSIGNED NOT NULL,
  `category_id` INT UNSIGNED NOT NULL,
  `allow`       TINYINT      NOT NULL DEFAULT 1 COMMENT '1=允许 0=禁止',
  `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_category` (`user_id`, `category_id`),
  KEY `idx_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='用户分类级权限(白名单/黑名单)';

-- -----------------------------------------------------------------------------
-- 5. 用户-视频 权限规则（单独放行 / 拉黑某个视频）
--    典型场景：允许 user1 看分类1，但禁止分类1下的视频99。
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `user_video_rule`;
CREATE TABLE `user_video_rule` (
  `id`         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`    INT UNSIGNED NOT NULL,
  `video_id`   INT UNSIGNED NOT NULL,
  `allow`      TINYINT      NOT NULL DEFAULT 0 COMMENT '1=强制放行 0=禁止(黑名单)',
  `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_video` (`user_id`, `video_id`),
  KEY `idx_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='用户视频级权限(黑名单/放行)';

-- -----------------------------------------------------------------------------
-- 6. 收藏表
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `favorite`;
CREATE TABLE `favorite` (
  `id`         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`    INT UNSIGNED NOT NULL,
  `video_id`   INT UNSIGNED NOT NULL,
  `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_video` (`user_id`, `video_id`),
  KEY `idx_user_time` (`user_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='收藏表';

-- -----------------------------------------------------------------------------
-- 7. 观看历史（记录上次观看位置 / 累计观看时长）
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `watch_history`;
CREATE TABLE `watch_history` (
  `id`             INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`        INT UNSIGNED NOT NULL,
  `video_id`       INT UNSIGNED NOT NULL,
  `last_position`  FLOAT        NOT NULL DEFAULT 0   COMMENT '上次观看位置(秒)',
  `duration`       FLOAT        NOT NULL DEFAULT 0   COMMENT '视频总时长(秒)',
  `progress`       FLOAT        NOT NULL DEFAULT 0   COMMENT '进度百分比 0-100',
  `watch_seconds`  FLOAT        NOT NULL DEFAULT 0   COMMENT '累计观看秒数',
  `finished`       TINYINT      NOT NULL DEFAULT 0   COMMENT '是否看完',
  `segment_id`     VARCHAR(40)  NOT NULL DEFAULT ''  COMMENT '最近一次播放会话ID',
  `created_at`     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_video` (`user_id`, `video_id`),
  KEY `idx_user_time` (`user_id`, `updated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='观看历史';

-- -----------------------------------------------------------------------------
-- 8. 播放会话（观看次数统计：单次会话累计观看 >= 10s 记 1 次）
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `view_session`;
CREATE TABLE `view_session` (
  `segment_id`    VARCHAR(40)  NOT NULL COMMENT '前端生成的播放会话ID',
  `user_id`       INT UNSIGNED NOT NULL,
  `video_id`      INT UNSIGNED NOT NULL,
  `watch_seconds` FLOAT        NOT NULL DEFAULT 0 COMMENT '本次会话累计观看秒数',
  `counted`       TINYINT      NOT NULL DEFAULT 0 COMMENT '是否已计入播放次数',
  `ip`            VARCHAR(64)  NOT NULL DEFAULT '',
  `user_agent`    VARCHAR(255) NOT NULL DEFAULT '',
  `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`segment_id`),
  KEY `idx_video` (`video_id`),
  KEY `idx_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='播放会话(播放次数统计用)';

-- -----------------------------------------------------------------------------
-- 9. 分片上传会话
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `upload_session`;
CREATE TABLE `upload_session` (
  `upload_id`     VARCHAR(40)  NOT NULL COMMENT '上传会话ID',
  `user_id`       INT UNSIGNED NOT NULL,
  `file_name`     VARCHAR(255) NOT NULL COMMENT '原始文件名',
  `file_hash`     VARCHAR(64)  NOT NULL DEFAULT '' COMMENT '整文件 hash，用于秒传/校验',
  `category_id`   INT UNSIGNED NOT NULL DEFAULT 0,
  `title`         VARCHAR(255) NOT NULL DEFAULT '',
  `total_size`    BIGINT       NOT NULL DEFAULT 0  COMMENT '文件总字节',
  `chunk_size`    INT          NOT NULL DEFAULT 0  COMMENT '分片大小(字节)',
  `total_chunks`  INT          NOT NULL DEFAULT 0  COMMENT '总分片数',
  `uploaded_chunks` INT        NOT NULL DEFAULT 0  COMMENT '已上传分片数',
  `stage`         VARCHAR(24)  NOT NULL DEFAULT 'init'
                  COMMENT '阶段: init/uploading/merging/probing/covering/finished/failed',
  `merged_bytes`  BIGINT       NOT NULL DEFAULT 0  COMMENT '合并已写入字节，用于合并进度',
  `percent`       FLOAT        NOT NULL DEFAULT 0  COMMENT '整体百分比 0-100',
  `speed`         BIGINT       NOT NULL DEFAULT 0  COMMENT '瞬时速度 字节/秒',
  `video_id`      INT UNSIGNED NOT NULL DEFAULT 0  COMMENT '合并成功后产生的视频ID',
  `message`       VARCHAR(500) NOT NULL DEFAULT '' COMMENT '阶段提示信息',
  `error`         VARCHAR(500) NOT NULL DEFAULT '' COMMENT '错误信息',
  `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`upload_id`),
  KEY `idx_user` (`user_id`),
  KEY `idx_stage` (`stage`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='分片上传会话';

-- -----------------------------------------------------------------------------
-- 10. 分片记录（支持断点续传，前端可查询已上传分片）
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `upload_chunk`;
CREATE TABLE `upload_chunk` (
  `id`         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `upload_id`  VARCHAR(40)  NOT NULL,
  `chunk_index` INT         NOT NULL COMMENT '分片序号，从 0 开始',
  `size`       INT          NOT NULL DEFAULT 0,
  `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_upload_chunk` (`upload_id`, `chunk_index`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='上传分片记录';

-- -----------------------------------------------------------------------------
-- 11. m3u8 链接下载导入任务
--     2026-09-26 由 update.sql 变更 #1 合并入基线。
--     承载「链接 -> 下载 -> 入库」全过程状态（底层为 N_m3u8DL-RE），字段语义与
--     upload_session 对齐，便于前端复用同一套进度展示；供管理端页面与浏览器插件
--     （X-API-Token 免登录通道）共同使用。
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `download_task`;
CREATE TABLE `download_task` (
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

SET FOREIGN_KEY_CHECKS = 1;

-- =============================================================================
--  初始化数据
-- =============================================================================

-- 管理员：admin / admin123
-- 测试用户：user1 / user123   user2 / user123
INSERT INTO `sys_user` (`username`, `password`, `nickname`, `role`, `status`, `remark`) VALUES
('admin', 'pbkdf2_sha256$120000$4ee57f4f929c6959237763adf5565755$4e193a16e9884470a57788cc17c669a57ef34ef1598ad751608a0b7c571b66b5', '超级管理员', 'admin', 1, '系统内置管理员，请及时修改密码'),
('user1', 'pbkdf2_sha256$120000$85a0ca7562ad1447a95429faa1efde17$bd0381de0f2ab8a7e99ef222f183ce3f47d5a90d1db89a8fbd9f8d9ccb7b89ad', '测试用户一', 'user', 1, '默认可见全部启用分类'),
('user2', 'pbkdf2_sha256$120000$85a0ca7562ad1447a95429faa1efde17$bd0381de0f2ab8a7e99ef222f183ce3f47d5a90d1db89a8fbd9f8d9ccb7b89ad', '测试用户二', 'user', 0, '默认被禁用，用于验证禁用逻辑');

-- 示例分类
INSERT INTO `category` (`name`, `description`, `sort`, `status`) VALUES
('电影',    '各类电影长片',       10, 1),
('电视剧',  '剧集内容',           20, 1),
('动漫',    '动画与番剧',         30, 1),
('纪录片',  '纪实类内容',         40, 1),
('教学',    '课程与教学视频',     50, 1),
('音乐',    'MV 与音乐现场',      60, 1);

-- 权限示例：user1 被限制为「只能看 电影 / 动漫 / 教学」，且【禁止】其中某个视频
-- （视频ID需要真实存在，此处仅作演示，实际请在管理端操作）
INSERT INTO `user_category_rule` (`user_id`, `category_id`, `allow`) VALUES
(2, 1, 1),
(2, 3, 1),
(2, 5, 1);
