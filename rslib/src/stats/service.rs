// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
use crate::collection::Collection;
use crate::error;
use crate::revlog::RevlogReviewKind;

impl crate::services::StatsService for Collection {
    fn card_stats(
        &mut self,
        input: anki_proto::cards::CardId,
    ) -> error::Result<anki_proto::stats::CardStatsResponse> {
        self.card_stats(input.cid.into())
    }

    fn get_review_logs(
        &mut self,
        input: anki_proto::cards::CardId,
    ) -> error::Result<anki_proto::stats::ReviewLogs> {
        self.get_review_logs(input.cid.into())
    }

    fn graphs(
        &mut self,
        input: anki_proto::stats::GraphsRequest,
    ) -> error::Result<anki_proto::stats::GraphsResponse> {
        self.graph_data_for_search(&input.search, input.days)
    }

    fn get_graph_preferences(&mut self) -> error::Result<anki_proto::stats::GraphPreferences> {
        Ok(Collection::get_graph_preferences(self))
    }

    fn set_graph_preferences(
        &mut self,
        input: anki_proto::stats::GraphPreferences,
    ) -> error::Result<()> {
        self.set_graph_preferences(input)
    }

    fn mcat_engine_status(&mut self) -> error::Result<anki_proto::stats::McatEngineStatusResponse> {
        Ok(anki_proto::stats::McatEngineStatusResponse {
            total_cards: self.storage.all_cards_count()?,
            engine_tag: "speedrun-ok".to_string(),
        })
    }

    fn mcat_mastery(
        &mut self,
        input: anki_proto::stats::McatMasteryRequest,
    ) -> error::Result<anki_proto::stats::McatMasteryResponse> {
        self.mcat_mastery(&input.search)
    }

    fn mcat_deck_score(
        &mut self,
        input: anki_proto::stats::McatDeckScoreRequest,
    ) -> error::Result<anki_proto::stats::McatDeckScoreResponse> {
        self.mcat_deck_score(&input.search)
    }

    fn mcat_pace(
        &mut self,
        input: anki_proto::stats::McatPaceRequest,
    ) -> error::Result<anki_proto::stats::McatPaceResponse> {
        self.mcat_pace(&input.search)
    }

    fn mcat_performance(
        &mut self,
        input: anki_proto::stats::McatPerformanceRequest,
    ) -> error::Result<anki_proto::stats::McatPerformanceResponse> {
        self.mcat_performance(&input.search)
    }

    fn mcat_readiness(
        &mut self,
        input: anki_proto::stats::McatReadinessRequest,
    ) -> error::Result<anki_proto::stats::McatReadinessResponse> {
        self.mcat_readiness(&input.search)
    }
}

impl From<RevlogReviewKind> for i32 {
    fn from(kind: RevlogReviewKind) -> Self {
        (match kind {
            RevlogReviewKind::Learning => anki_proto::stats::revlog_entry::ReviewKind::Learning,
            RevlogReviewKind::Review => anki_proto::stats::revlog_entry::ReviewKind::Review,
            RevlogReviewKind::Relearning => anki_proto::stats::revlog_entry::ReviewKind::Relearning,
            RevlogReviewKind::Filtered => anki_proto::stats::revlog_entry::ReviewKind::Filtered,
            RevlogReviewKind::Manual => anki_proto::stats::revlog_entry::ReviewKind::Manual,
            RevlogReviewKind::Rescheduled => {
                anki_proto::stats::revlog_entry::ReviewKind::Rescheduled
            }
        }) as i32
    }
}
