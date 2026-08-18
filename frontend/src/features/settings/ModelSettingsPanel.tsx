import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchModelSettings,
  modelSettingsQueryKey,
  updateModelSettings,
  type ModelSelection,
} from "../../api/modelSettings";

export function ModelSettingsPanel() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: modelSettingsQueryKey, queryFn: fetchModelSettings });
  const [draftOverride, setDraftOverride] = useState<ModelSelection | null>(null);
  const update = useMutation({
    mutationFn: updateModelSettings,
    onSuccess: (response) => {
      setDraftOverride(null);
      queryClient.setQueryData(modelSettingsQueryKey, response);
    },
  });

  const draft = draftOverride ?? query.data?.selection ?? null;

  const selectedSource = useMemo(
    () => query.data?.sources.find((source) => source.id === draft?.source_id),
    [draft?.source_id, query.data?.sources],
  );
  const dirty = draft !== null && query.data !== undefined
    && (draft.source_id !== query.data.selection.source_id || draft.model_id !== query.data.selection.model_id);

  const selectSource = (sourceId: ModelSelection["source_id"]) => {
    const source = query.data?.sources.find((item) => item.id === sourceId);
    const model = source?.models.find((item) => item.available) ?? source?.models[0];
    if (model !== undefined) setDraftOverride({ source_id: sourceId, model_id: model.id });
  };

  return (
    <section className="model-settings" aria-labelledby="model-settings-heading">
      <p className="editorial-label">模型来源</p>
      <h1 id="model-settings-heading">选择模型来源</h1>
      <p className="settings-intro">此偏好用于 Personalization、Brief 与 Ask；共享 Event 事实继续使用服务器默认模型。</p>

      {query.isPending && <p role="status">正在加载模型设置…</p>}
      {query.isError && <p className="auth-error" role="alert">无法加载模型设置，请刷新后重试。</p>}
      {query.data !== undefined && draft !== null && (
        <form className="model-settings-form" onSubmit={(event) => { event.preventDefault(); update.mutate(draft); }}>
          <label className="model-select-row">
            <span>模型来源</span>
            <select
              aria-label="模型来源"
              disabled={update.isPending}
              onChange={(event) => selectSource(event.target.value as ModelSelection["source_id"])}
              value={draft.source_id}
            >
              {query.data.sources.map((source) => <option disabled={!source.available} key={source.id} value={source.id}>{source.label}</option>)}
            </select>
          </label>
          <label className="model-select-row">
            <span>模型</span>
            <select
              aria-label="模型"
              disabled={update.isPending}
              onChange={(event) => setDraftOverride({ ...draft, model_id: event.target.value as ModelSelection["model_id"] })}
              value={draft.model_id}
            >
              {selectedSource?.models.map((model) => <option disabled={!model.available} key={model.id} value={model.id}>{model.label}</option>)}
            </select>
          </label>
          <button className="auth-submit" disabled={!dirty || update.isPending} type="submit">
            {update.isPending ? "保存中…" : "保存模型"}
          </button>
          {update.isSuccess && !dirty && <p className="settings-success" role="status">模型偏好已保存。</p>}
          {update.isError && <p className="auth-error" role="alert">无法保存该模型，请确认服务器已配置。</p>}
        </form>
      )}
    </section>
  );
}
