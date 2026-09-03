const path = require('path');
const webpack = require('webpack');

module.exports = {
  entry: './web/main.js',
  output: {
    path: path.resolve(__dirname, 'web-dist'),
    filename: 'bundle.js',
    clean: true
  },
  resolve: {
    extensions: ['.js'],
    fallback: {
      buffer: require.resolve('buffer/'),
      process: require.resolve('process/browser')
    }
  },
  plugins: [
    new webpack.ProvidePlugin({
      Buffer: ['buffer', 'Buffer'],
      process: 'process/browser'
    })
  ],
  devtool: false,
  performance: { hints: false }
};
