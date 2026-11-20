#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { GwSfnStack } from '../lib/gwsfn-stack';

const app = new cdk.App();
new GwSfnStack(app, 'GwSfnStack', {
  env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION ?? 'us-west-2' },
});
