claude "In backend/data/models.py, define all Pydantic + SQLAlchemy models for TipMind:

Pydantic models:
- VideoEvent(video_id, creator_id, creator_name, title, duration_seconds, timestamp)
- WatchEvent(user_id, video_id, watch_seconds, total_duration, percentage_watched)
- ChatMessage(user_id, video_id, message, timestamp, sentiment_score)
- MilestoneEvent(creator_id, milestone_type: enum[LIKES_10K, VIEWS_100K, SUBS_MILESTONE, DEBATE_WIN, CUSTOM], value, timestamp)
- SwarmGoal(swarm_id, creator_id, goal_description, trigger_event, target_amount_usd, current_amount_usd, participant_count, status: enum[ACTIVE, TRIGGERED, COMPLETED, EXPIRED])
- TipDecision(agent_type, trigger, amount_usd, token, creator_id, reasoning, confidence_score)
- TipTransaction(tx_hash, from_wallet, to_wallet, amount, token, creator_id, trigger_type, status, timestamp)

SQLAlchemy tables:
- tip_transactions
- swarm_goals
- swarm_participants
- agent_decisions_log
- user_preferences

In backend/data/database.py:
- Async SQLAlchemy engine setup
- create_all_tables() function
- get_db() dependency for FastAPI"