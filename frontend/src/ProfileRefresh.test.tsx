import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ProfileResponse } from './api/types';
import { App } from './App';
import { HEALTH, jsonResponse, PROFILE_RESPONSE, sse, streamResponse } from './test/fixtures';

const SAA = 'AWS Certified Solutions Architect - Associate';
const NOTE = { kind: 'certification', text: `Earned the ${SAA} certification`, skill: 'AWS', created_at: '2026-10-26T17:00:00Z' };

const V1: ProfileResponse = {
  ...PROFILE_RESPONSE,
  profile: {
    ...PROFILE_RESPONSE.profile,
    opportunities: [
      { title: SAA, action: 'Book the SAA-C03 exam', timeframe: 'this quarter', related_skills: ['AWS'] },
      ...PROFILE_RESPONSE.profile.opportunities,
    ],
  },
};

const V2: ProfileResponse = {
  profile: {
    ...V1.profile,
    version: 2,
    origin: 'refresh',
    created_at: '2026-10-26T17:00:05Z',
    headline: 'Certified AWS builder moving into ML engineering',
    goal_alignment: 58,
    skills: [
      ...V1.profile.skills,
      { name: 'AWS', category: 'tool', level: 3, relevance: 'high', evidence: [NOTE.text] },
    ],
    weaknesses: [{ area: 'Model deployment at scale', why_it_matters: 'Core to ML engineering', severity: 'medium' }],
    opportunities: [
      { title: 'Serve the review classifier on SageMaker', action: 'Deploy it behind an endpoint', timeframe: 'this month', related_skills: ['AWS'] },
    ],
  },
  insights: {
    ...V1.insights,
    stats: { ...V1.insights.stats, goal_alignment: 58, focus_area: 'Model deployment at scale' },
    trends: {
      ...V1.insights.trends,
      snapshots: [
        ...V1.insights.trends.snapshots,
        { version: 2, created_at: '2026-10-26T17:00:05Z', goal_alignment: 58, readiness_pct: 67, skills_total: 3, avg_level: 3.3 },
      ],
    },
  },
};

describe('chat-driven profile refresh', () => {
  it('replaces the whole profile and insights in place when profile_updated arrives', async () => {
    const user = userEvent.setup();
    localStorage.setItem('career-coach:user', JSON.stringify({ userId: 'jordan-ab12', name: 'Jordan' }));
    const chat =
      sse({ type: 'memory', note: NOTE }) +
      sse({ type: 'profile_refresh', state: 'active', detail: 'Refreshing your profile from version 1' }) +
      sse({ type: 'profile_updated', ...V2 }) +
      sse({ type: 'delta', text: 'Congratulations on the certification!' }) +
      sse({ type: 'done', text: 'Congratulations on the certification!', tools: [], recorded: NOTE, profile_version: 2 });
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('/api/health')) return jsonResponse(200, HEALTH);
      if (url.endsWith('/profile')) return jsonResponse(200, V1);
      // the insights fetch the saved note triggers can lose the race: it still describes version 1
      if (url.endsWith('/insights')) return jsonResponse(200, V1.insights);
      if (url.endsWith('/chat')) return streamResponse([chat.slice(0, 90), chat.slice(90)]);
      return jsonResponse(404, {});
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    expect(await screen.findByRole('heading', { name: 'CS student who ships data pipelines' })).toBeInTheDocument();
    const profilePanel = () => within(document.getElementById('panel-profile')!);
    expect(profilePanel().getByText(`${SAA}:`)).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Coach' }));
    await user.type(screen.getByLabelText('Message the coach'), `I earned the ${SAA}! Update my profile.{Enter}`);
    expect(await screen.findByText('Profile refreshed to version 2.')).toBeInTheDocument();
    expect(screen.getByText('Congratulations on the certification!')).toBeInTheDocument();

    // Profile tab: the new version, without a reload
    await user.click(screen.getByRole('tab', { name: 'Profile' }));
    expect(screen.getByRole('heading', { name: 'Certified AWS builder moving into ML engineering' })).toBeInTheDocument();
    expect(profilePanel().queryByText(`${SAA}:`)).not.toBeInTheDocument();
    expect(profilePanel().getByText('Serve the review classifier on SageMaker:')).toBeInTheDocument();
    expect(profilePanel().getByText(NOTE.text)).toBeInTheDocument();
    expect(profilePanel().getByText('Model deployment at scale')).toBeInTheDocument();

    // Insights tab: version 2's numbers, not the stale version 1 insights fetched mid-stream
    await user.click(screen.getByRole('tab', { name: 'Insights' }));
    const insights = within(document.getElementById('panel-insights')!);
    expect(insights.getByText('58')).toBeInTheDocument();
    expect(insights.getAllByText('Model deployment at scale').length).toBeGreaterThan(0);

    const profileLoads = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/profile'));
    expect(profileLoads).toHaveLength(1); // no reload
    // the chat stayed mounted while hidden: its transcript is still there
    await user.click(screen.getByRole('tab', { name: 'Coach' }));
    expect(screen.getByText('Profile refreshed to version 2.')).toBeInTheDocument();
  });
});
