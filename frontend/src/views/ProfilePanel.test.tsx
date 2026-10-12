import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Opportunity } from '../api/types';
import { PROFILE_RESPONSE } from '../test/fixtures';
import { ProfilePanel } from './ProfilePanel';

const step = (title: string, extra: Partial<Opportunity>): Opportunity => ({
  title,
  action: `Do ${title}`,
  timeframe: 'this quarter',
  related_skills: [],
  ...extra,
});

describe('ProfilePanel next-step checks', () => {
  it('shows what the web check found for each next step', () => {
    const opportunities = [
      step('AWS Certified Cloud Practitioner', {
        verification: 'verified', source_title: 'AWS Certified Cloud Practitioner (CLF-C02)',
        source_url: 'https://aws.amazon.com/certification/certified-cloud-practitioner/',
      }),
      step('AWS Certified AI Practitioner', {
        verification: 'corrected', original_title: 'AWS AI Advocate Certification',
        source_title: 'AWS Certified AI Practitioner', source_url: 'https://aws.amazon.com/certification/certified-ai-practitioner/',
      }),
      step('Galactic Cloud Wizard Badge', { verification: 'unverified' }),
      step('Mock interviews', { verification: 'general' }),
      step('Old profile step', {}), // saved before checks existed
    ];
    render(<ProfilePanel profile={{ ...PROFILE_RESPONSE.profile, opportunities }} />);

    expect(screen.getByText('Verified online')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /AWS Certified Cloud Practitioner \(CLF-C02\)/ }))
      .toHaveAttribute('href', 'https://aws.amazon.com/certification/certified-cloud-practitioner/');
    expect(screen.getByText(/suggested “AWS AI Advocate Certification”, which no search result names/)).toBeInTheDocument();
    expect(screen.getByText('Couldn’t verify')).toBeInTheDocument();
    // general advice and older profiles carry no note at all
    expect(screen.getAllByText(/Verified online|Corrected|Couldn’t verify|Not checked/)).toHaveLength(3);
  });
});
