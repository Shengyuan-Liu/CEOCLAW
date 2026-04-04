"""
长期记忆 (Long-term Memory)
持久化存储项目信息，支持跨会话访问
"""
from typing import Dict, Any, List, Optional
import json
import os
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class LongTermMemory:
    """
    长期记忆：持久化项目信息
    - 项目偏好（目标市场、技术栈、品牌风格等）
    - 历史决策记录
    - 统计信息
    """

    def __init__(self, user_id: str, storage_path: str = "data/memory"):
        """
        初始化长期记忆

        Args:
            user_id: 用户ID
            storage_path: 存储路径
        """
        self.user_id = user_id
        self.storage_path = storage_path
        self.db_path = os.path.join(storage_path, f"{user_id}.json")

        # 确保存储目录存在
        Path(storage_path).mkdir(parents=True, exist_ok=True)

        # 加载或初始化数据
        self.data = self._load()
        logger.info(f"Long-term memory initialized for user: {user_id}")

    def _load(self) -> Dict[str, Any]:
        """从文件加载数据"""
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logger.debug(f"Loaded long-term memory from {self.db_path}")

                    data = self._ensure_fields(data)
                    return data
            except Exception as e:
                logger.error(f"Failed to load long-term memory: {e}")
                return self._init_data()
        else:
            logger.info("No existing long-term memory, creating new")
            return self._init_data()

    def _ensure_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        确保必需字段存在，防止手动编辑JSON导致字段缺失

        Args:
            data: 原始数据

        Returns:
            补全后的数据
        """
        defaults = self._init_data()
        for key, value in defaults.items():
            if key not in data:
                data[key] = value
        if "total_messages" not in data.get("statistics", {}):
            data["statistics"]["total_messages"] = 0

        return data

    def _init_data(self) -> Dict[str, Any]:
        """初始化数据结构"""
        return {
            "user_id": self.user_id,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "preferences": [],  # 偏好列表: [{"type": "target_market", "value": "B2B SaaS"}, ...]
            "chat_history": [],  # 所有聊天记录（跨会话）
            "project_history": [],  # 所有项目决策记录
            "statistics": {
                "total_projects": 0,
                "total_messages": 0,
                "frequent_actions": {}
            }
        }

    def _save(self):
        """保存数据到文件"""
        try:
            self.data["updated_at"] = datetime.now().isoformat()
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            logger.debug(f"Saved long-term memory to {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to save long-term memory: {e}")

    def save_preference(self, pref_type: str, value: Any):
        """
        保存项目偏好（列表格式）

        Args:
            pref_type: 偏好类型
            value: 偏好值
        """
        # 查找是否已存在该类型的偏好
        preferences = self.data["preferences"]
        found = False

        for pref in preferences:
            if pref.get("type") == pref_type:
                pref["value"] = value
                found = True
                break

        # 如果不存在，添加新的偏好
        if not found:
            preferences.append({"type": pref_type, "value": value})

        self._save()
        logger.info(f"Saved preference: {pref_type} = {value}")

    def get_preference(self, pref_type: str = None) -> Any:
        """
        获取项目偏好

        Args:
            pref_type: 偏好类型，None返回字典格式的全部偏好

        Returns:
            偏好值或偏好字典
        """
        preferences = self.data["preferences"]

        if pref_type is None:
            # 返回字典格式，方便调用方使用
            result = {}
            for pref in preferences:
                result[pref.get("type")] = pref.get("value")
            return result
        else:
            # 查找特定类型的偏好
            for pref in preferences:
                if pref.get("type") == pref_type:
                    return pref.get("value")
            return None

    def add_chat_message(self, role: str, content: str, session_id: str = None):
        """
        添加聊天消息到长期记忆

        Args:
            role: 角色 (user/assistant)
            content: 消息内容
            session_id: 会话ID（可选）
        """
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id
        }

        self.data["chat_history"].append(message)
        self.data["statistics"]["total_messages"] += 1
        self._save()
        logger.debug(f"Added chat message to long-term memory: {role}")

    def get_chat_history(self, limit: int = None, session_id: str = None) -> List[Dict[str, Any]]:
        """
        获取聊天历史

        Args:
            limit: 返回数量限制
            session_id: 会话ID（只返回特定会话的消息）

        Returns:
            消息列表
        """
        messages = self.data["chat_history"]

        if session_id:
            messages = [m for m in messages if m.get("session_id") == session_id]

        if limit:
            return messages[-limit:]
        return messages

    def save_project_history(self, project_info: Dict[str, Any]):
        """
        保存项目决策历史

        Args:
            project_info: 项目决策信息
        """
        project_record = {
            "record_id": f"record_{len(self.data['project_history']) + 1}",
            "timestamp": datetime.now().isoformat(),
            **project_info
        }

        self.data["project_history"].append(project_record)

        # 更新统计信息
        self.data["statistics"]["total_projects"] += 1

        # 更新常用操作统计
        action_type = project_info.get("action_type")
        if action_type:
            freq = self.data["statistics"]["frequent_actions"]
            freq[action_type] = freq.get(action_type, 0) + 1

        self._save()
        logger.info(f"Saved project history: {project_record['record_id']}")

    def get_project_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取历史项目决策

        Args:
            limit: 返回数量限制

        Returns:
            项目决策列表
        """
        return self.data["project_history"][-limit:] if limit else self.data["project_history"]

    def get_frequent_actions(self, top_n: int = 5) -> List[tuple]:
        """
        获取常用操作

        Args:
            top_n: 返回前N个

        Returns:
            [(action_type, count), ...]
        """
        freq = self.data["statistics"]["frequent_actions"]
        sorted_actions = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return sorted_actions[:top_n]

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self.data["statistics"].copy()

    def clear_history(self):
        """清空历史记录（保留偏好）"""
        self.data["chat_history"] = []
        self.data["project_history"] = []
        self.data["statistics"]["total_projects"] = 0
        self.data["statistics"]["total_messages"] = 0
        self.data["statistics"]["frequent_actions"] = {}
        self._save()
        logger.info("Cleared all history (chat + projects)")

    def delete_all(self):
        """删除所有数据（包括文件）"""
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
            logger.warning(f"Deleted long-term memory file: {self.db_path}")
