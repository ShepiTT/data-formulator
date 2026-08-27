// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

/**
 * 团队协作面板（局域网协作码模式）。
 *
 * 创建团队 → 生成 4 位协作码；同事在同一局域网内输入协作码加入。
 * 共享：主机指定的共享文件夹（双向）+ 主机勾选的模型（经主机中转，
 * 密钥不出主机）。聊天与会话始终保留在各自电脑上，不共享。
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
    Box, Button, Checkbox, Chip, CircularProgress, Dialog, DialogActions,
    DialogContent, DialogTitle, Divider, FormControlLabel, IconButton,
    TextField, Tooltip, Typography,
} from '@mui/material';
import Diversity3Icon from '@mui/icons-material/Diversity3';
import RefreshIcon from '@mui/icons-material/Refresh';
import PersonRemoveIcon from '@mui/icons-material/PersonRemove';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import { useDispatch, useSelector } from 'react-redux';

import { AppDispatch } from '../app/store';
import { DataFormulatorState, dfActions, fetchUserModels } from '../app/dfSlice';
import { apiRequest, ApiRequestError } from '../app/apiClient';
import { textVar } from '../app/layout';

const TEAM_API = '/api/team';

interface TeamMember { id: string; name: string; ip: string; joined_at: number }

interface TeamStatus {
    mode: 'off' | 'host' | 'member';
    team_name?: string;
    code?: string;
    shared_folder?: string;
    shared_model_ids?: string[];
    members?: TeamMember[];
    lan_ips?: string[];
    host_url?: string;
    member_name?: string;
}

const post = (path: string, body?: object) => apiRequest(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
});

const errText = (e: unknown) =>
    e instanceof ApiRequestError ? e.apiError.message : e instanceof Error ? e.message : String(e);

/** 大号显示的 4 位协作码 */
const CodeDisplay: React.FC<{ code: string }> = ({ code }) => (
    <Box sx={{ display: 'flex', gap: 1.5, justifyContent: 'center', my: 1 }}>
        {code.split('').map((d, i) => (
            <Box key={i} sx={{
                width: 52, height: 64, display: 'flex', alignItems: 'center', justifyContent: 'center',
                border: '2px solid', borderColor: 'primary.main', borderRadius: 2,
                fontSize: 34, fontWeight: 600, color: 'primary.main',
                fontFamily: 'var(--df-font-mono)',
            }}>{d}</Box>
        ))}
    </Box>
);

export const TeamCollabButton: React.FC = () => {
    const dispatch = useDispatch<AppDispatch>();
    const userModels = useSelector((state: DataFormulatorState) => state.models) ?? [];

    const [open, setOpen] = useState(false);
    const [status, setStatus] = useState<TeamStatus>({ mode: 'off' });
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    // 创建表单
    const [teamName, setTeamName] = useState('');
    const [sharedFolder, setSharedFolder] = useState('');
    // 加入表单
    const [joinCode, setJoinCode] = useState('');
    const [joinBusy, setJoinBusy] = useState(false);
    // 成员：上传
    const [uploading, setUploading] = useState(false);
    const uploadRef = React.useRef<HTMLInputElement>(null);

    const refresh = useCallback(async () => {
        try {
            const { data } = await apiRequest(`${TEAM_API}/status`);
            setStatus(data);
        } catch { /* 后端未就绪时静默 */ }
    }, []);

    useEffect(() => { refresh(); }, [refresh]);
    useEffect(() => {
        if (!open) return;
        refresh();
        const timer = setInterval(refresh, 5000);
        return () => clearInterval(timer);
    }, [open, refresh]);

    const run = async (fn: () => Promise<unknown>) => {
        setBusy(true); setError('');
        try { await fn(); await refresh(); }
        catch (e) { setError(errText(e)); }
        finally { setBusy(false); }
    };

    const handleCreate = () => run(async () => {
        await post(`${TEAM_API}/host/start`, {
            team_name: teamName.trim(), shared_folder: sharedFolder.trim(),
        });
    });

    const handleJoin = async () => {
        setJoinBusy(true); setError('');
        try {
            const { data } = await post(`${TEAM_API}/join-team`, { code: joinCode.trim() });
            await refresh();
            dispatch(fetchUserModels());
            dispatch(dfActions.addMessages({
                timestamp: Date.now(), type: 'success', component: '团队协作',
                value: `已加入「${data.team_name}」。共享模型与「团队共享」数据源已就绪（数据连接器面板中可见）。`,
            }));
        } catch (e) { setError(errText(e)); }
        finally { setJoinBusy(false); }
    };

    const handleLeave = () => run(async () => {
        await post(`${TEAM_API}/leave`);
        dispatch(fetchUserModels());
    });

    const handleStop = () => run(() => post(`${TEAM_API}/host/stop`));
    const handleRegenerate = () => run(() => post(`${TEAM_API}/host/regenerate-code`));
    const handleKick = (memberId: string) => run(() => post(`${TEAM_API}/host/kick`, { member_id: memberId }));

    const toggleSharedModel = (modelId: string) => {
        const current = status.shared_model_ids ?? [];
        const next = current.includes(modelId)
            ? current.filter(id => id !== modelId)
            : [...current, modelId];
        run(() => post(`${TEAM_API}/host/settings`, { shared_model_ids: next }));
    };

    const handleUpload = async (file: File) => {
        setUploading(true); setError('');
        try {
            const form = new FormData();
            form.append('file', file);
            await apiRequest(`${TEAM_API}/upload-file`, { method: 'POST', body: form });
            dispatch(dfActions.addMessages({
                timestamp: Date.now(), type: 'success', component: '团队协作',
                value: `「${file.name}」已上传到团队共享文件夹。`,
            }));
        } catch (e) { setError(errText(e)); }
        finally { setUploading(false); }
    };

    const active = status.mode !== 'off';
    const ownModels = userModels.filter(m => !m.id.startsWith('team-'));

    return (<>
        <Tooltip title={active ? `团队协作 · ${status.team_name ?? ''}` : '团队协作'} placement="right">
            <IconButton size="small" onClick={() => setOpen(true)} sx={{
                color: active ? 'success.main' : 'text.secondary',
                borderRadius: 1,
            }}>
                <Diversity3Icon fontSize="small" />
            </IconButton>
        </Tooltip>

        <Dialog open={open} onClose={() => setOpen(false)} maxWidth="sm" fullWidth>
            <DialogTitle sx={{ fontSize: textVar.xl }}>
                团队协作
                {active && <Chip size="small" color="success" label={status.mode === 'host' ? '主持中' : '已加入'} sx={{ ml: 1.5 }} />}
            </DialogTitle>
            <DialogContent>
                {error && (
                    <Typography color="error" variant="body2" sx={{ mb: 1.5 }}>{error}</Typography>
                )}

                {status.mode === 'off' && (
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <Typography variant="body2" color="text.secondary">
                            在同一局域网内与同事共享数据文件和 AI 模型。聊天与会话不共享，
                            始终保留在各自的电脑上。适用于办公室等可信网络。
                        </Typography>

                        <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 2 }}>
                            <Typography sx={{ fontWeight: 600, mb: 1 }}>创建团队（我来当主机）</Typography>
                            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                                <TextField size="small" label="团队名称" placeholder="例如：会计分析小组"
                                    value={teamName} onChange={e => setTeamName(e.target.value)} />
                                <TextField size="small" label="共享文件夹路径（可稍后设置）"
                                    placeholder="例如 D:\\团队数据"
                                    value={sharedFolder} onChange={e => setSharedFolder(e.target.value)} />
                                <Button variant="contained" disabled={busy} onClick={handleCreate}>
                                    {busy ? <CircularProgress size={18} /> : '创建团队，生成协作码'}
                                </Button>
                            </Box>
                        </Box>

                        <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 2 }}>
                            <Typography sx={{ fontWeight: 600, mb: 1 }}>加入团队</Typography>
                            <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'center' }}>
                                <TextField size="small" label="4 位协作码" value={joinCode}
                                    onChange={e => setJoinCode(e.target.value.replace(/\D/g, '').slice(0, 4))}
                                    inputProps={{ style: { fontSize: 22, letterSpacing: 8, textAlign: 'center', fontFamily: 'var(--df-font-mono)' } }}
                                    sx={{ width: 170 }} />
                                <Button variant="contained" disabled={joinBusy || joinCode.length !== 4} onClick={handleJoin}>
                                    {joinBusy ? <CircularProgress size={18} /> : '加入'}
                                </Button>
                            </Box>
                            <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                                向发起人索要协作码；双方需在同一局域网内。
                            </Typography>
                        </Box>
                    </Box>
                )}

                {status.mode === 'host' && (
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                        <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center' }}>
                            团队「{status.team_name}」的协作码——告诉同事即可加入
                        </Typography>
                        <CodeDisplay code={status.code ?? '----'} />
                        <Box sx={{ display: 'flex', justifyContent: 'center', gap: 1 }}>
                            <Button size="small" startIcon={<RefreshIcon />} disabled={busy} onClick={handleRegenerate}>
                                换一个码
                            </Button>
                        </Box>
                        {(status.lan_ips?.length ?? 0) > 0 && (
                            <Typography variant="caption" color="text.secondary" sx={{ textAlign: 'center' }}>
                                本机局域网地址：{status.lan_ips!.join('、')}
                            </Typography>
                        )}

                        <Divider />
                        <TextField size="small" label="共享文件夹（团队成员可读取和上传）"
                            value={status.shared_folder ?? ''} placeholder="例如 D:\\团队数据"
                            onChange={e => setStatus(s => ({ ...s, shared_folder: e.target.value }))}
                            onBlur={e => run(() => post(`${TEAM_API}/host/settings`, { shared_folder: e.target.value.trim() }))} />

                        <Typography sx={{ fontWeight: 600, fontSize: textVar.md }}>共享给团队的模型（成员用量计入你的账户）</Typography>
                        {ownModels.length === 0 && (
                            <Typography variant="caption" color="text.secondary">尚未配置任何模型。</Typography>
                        )}
                        {ownModels.map(m => (
                            <FormControlLabel key={m.id} sx={{ ml: 0.5, '& .MuiTypography-root': { fontSize: textVar.md } }}
                                control={<Checkbox size="small"
                                    checked={(status.shared_model_ids ?? []).includes(m.id)}
                                    onChange={() => toggleSharedModel(m.id)} />}
                                label={`${m.model}（${m.endpoint}）`} />
                        ))}

                        <Divider />
                        <Typography sx={{ fontWeight: 600, fontSize: textVar.md }}>
                            成员（{status.members?.length ?? 0}）
                        </Typography>
                        {(status.members ?? []).map(m => (
                            <Box key={m.id} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                <Typography variant="body2" sx={{ flex: 1 }}>{m.name}
                                    <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>{m.ip}</Typography>
                                </Typography>
                                <Tooltip title="移除成员">
                                    <IconButton size="small" onClick={() => handleKick(m.id)}>
                                        <PersonRemoveIcon fontSize="small" />
                                    </IconButton>
                                </Tooltip>
                            </Box>
                        ))}
                        {(status.members?.length ?? 0) === 0 && (
                            <Typography variant="caption" color="text.secondary">还没有成员加入。</Typography>
                        )}
                    </Box>
                )}

                {status.mode === 'member' && (
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                        <Typography variant="body2">
                            已加入团队「<b>{status.team_name}</b>」（主机 {status.host_url}）。
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                            · 主机共享的文件在左侧「数据连接器」面板的 <b>团队共享</b> 数据源里，点击即可加载分析。<br />
                            · 主机共享的模型已出现在「选择模型」列表中（带"团队共享"标识）。<br />
                            · 你的聊天与会话仍保存在自己电脑上，团队其他人看不到。
                        </Typography>
                        <Button variant="outlined" startIcon={uploading ? <CircularProgress size={16} /> : <UploadFileIcon />}
                            disabled={uploading} onClick={() => uploadRef.current?.click()}>
                            上传文件到团队共享
                        </Button>
                        <input ref={uploadRef} type="file" hidden accept=".csv,.tsv,.xlsx,.xls,.json,.jsonl,.parquet"
                            onChange={e => { const f = e.target.files?.[0]; if (f) handleUpload(f); e.target.value = ''; }} />
                    </Box>
                )}
            </DialogContent>
            <DialogActions>
                {status.mode === 'host' && (
                    <Button color="error" disabled={busy} onClick={handleStop}>解散团队</Button>
                )}
                {status.mode === 'member' && (
                    <Button color="error" disabled={busy} onClick={handleLeave}>退出团队</Button>
                )}
                <Button onClick={() => setOpen(false)}>关闭</Button>
            </DialogActions>
        </Dialog>
    </>);
};
